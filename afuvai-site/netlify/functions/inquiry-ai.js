/* ================================================================
   AFUVAI — Consultation form AI triage
   Triggered by: Netlify Forms outgoing webhook on the "consultation" form
   Setup: Netlify UI → Site settings → Forms → Outgoing notifications
          → Add webhook → URL: https://afuvai.com/.netlify/functions/inquiry-ai

   Sends two emails on each consultation submission:
     1. Client acknowledgment (warm, personalised, instant)
     2. Ami's ops brief (AI-parsed summary + suggested questions)

   Env vars required:
     ANTHROPIC_API_KEY  — from console.anthropic.com
     RESEND_API_KEY     — from resend.com
     OPS_EMAIL          — Ami's email, default: hello@afuvai.com
     FROM_EMAIL         — verified Resend sender, default: noreply@afuvai.com
   ================================================================ */

const Anthropic = require("@anthropic-ai/sdk");
const { Resend } = require("resend");

exports.handler = async function (event) {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: "Method Not Allowed" };
  }

  let submission;
  try {
    submission = JSON.parse(event.body);
  } catch {
    return { statusCode: 400, body: "Invalid JSON" };
  }

  // Netlify Forms webhook payload: { data: { name, email, ... }, ... }
  const data = submission.data || {};
  const clientName = data.name || submission.name || "there";
  const clientEmail = data.email || submission.email || "";
  const occasion = data.occasion || "";
  const date = data.date || "";
  const guests = data.guests || "";
  const venue = data.venue || "";
  const budget = data.budget || "";
  const vision = data.message || "";

  if (!clientEmail) {
    return { statusCode: 400, body: "No email in submission" };
  }

  const opsEmail = process.env.OPS_EMAIL || "hello@afuvai.com";
  const fromEmail = process.env.FROM_EMAIL || "noreply@afuvai.com";

  // Call Claude Haiku to generate both email drafts in one shot
  let clientEmailText = "";
  let opsBriefText = "";

  try {
    const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

    const prompt = `You are assisting AFUVAI Society, a luxury floral design studio in Las Vegas founded by Ami Nelson. A new consultation request just came in. Write two pieces of text, returned as valid JSON.

INQUIRY DETAILS:
- Client name: ${clientName}
- Occasion: ${occasion || "not specified"}
- Event date: ${date || "not specified"}
- Guest count: ${guests || "not specified"}
- Venue / location: ${venue || "not specified"}
- Budget: ${budget || "not specified"}
- Vision / message: ${vision || "not provided"}

Return ONLY a JSON object with exactly these two keys:

{
  "clientEmail": "A warm, elegant, 3-4 sentence acknowledgment email body to send to the client. Address them by first name. Mention the key details of their request. Tell them Ami will respond within one business day. Keep it luxurious, personal, not corporate. Do not include a subject line or greeting header — just the body text starting with 'Hi [first name],'",
  "opsBrief": "A concise ops brief for Ami (the designer). Start with a one-line summary: name, occasion, date, venue, budget. Then 2-3 bullet points: (1) what the client described wanting, (2) key details to note (size, complexity, timeline), (3) 2 suggested questions Ami should ask in the consultation. Keep it scannable and practical."
}`;

    const message = await anthropic.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 800,
      messages: [{ role: "user", content: prompt }],
    });

    const raw = message.content[0].text.trim();
    // Strip markdown code fences if present
    const jsonStr = raw.replace(/^```json?\s*/i, "").replace(/\s*```$/i, "").trim();
    const parsed = JSON.parse(jsonStr);
    clientEmailText = parsed.clientEmail || "";
    opsBriefText = parsed.opsBrief || "";
  } catch (err) {
    console.error("Claude API error:", err.message || err);
    // Fallback: plain acknowledgment
    clientEmailText = `Hi ${clientName.split(" ")[0]},\n\nThank you for reaching out to AFUVAI Society. We've received your ${occasion || "inquiry"} request and Ami will be in touch within one business day to discuss your vision.\n\nIn the meantime, feel free to browse our portfolio at https://afuvai.com/portfolio.html.\n\nWith warmth,\nAFUVAI Society`;
    opsBriefText = `New ${occasion} inquiry from ${clientName} (${clientEmail}).\nDate: ${date || "TBD"} | Venue: ${venue || "TBD"} | Budget: ${budget || "TBD"}\nVision: ${vision}`;
  }

  const resend = new Resend(process.env.RESEND_API_KEY);

  const occasionLabel = occasion ? ` — ${occasion}` : "";
  const errors = [];

  // 1. Client acknowledgment
  try {
    await resend.emails.send({
      from: `AFUVAI Society <${fromEmail}>`,
      to: clientEmail,
      subject: `We've received your request${occasionLabel} | AFUVAI Society`,
      text: `${clientEmailText}\n\n---\nAFUVAI Society | Las Vegas\nhello@afuvai.com | afuvai.com`,
    });
  } catch (err) {
    errors.push("client-email: " + (err.message || err));
    console.error("Client email send error:", err.message || err);
  }

  // 2. Ami's ops brief
  const BAR = "─".repeat(56);
  const opsBody = [
    `AFUVAI SOCIETY — NEW CONSULTATION INQUIRY`,
    BAR,
    ``,
    `Client    ${clientName}`,
    `Email     ${clientEmail}`,
    `Phone     ${data.phone || "not provided"}`,
    `Occasion  ${occasion || "not specified"}`,
    `Date      ${date || "not specified"}`,
    `Guests    ${guests || "not specified"}`,
    `Venue     ${venue || "not specified"}`,
    `Budget    ${budget || "not specified"}`,
    ``,
    BAR,
    `AI BRIEF`,
    BAR,
    opsBriefText,
    ``,
    BAR,
    `FULL MESSAGE FROM CLIENT`,
    BAR,
    vision || "(no message provided)",
    ``,
    `Reply-to: ${clientEmail}`,
  ].join("\n");

  try {
    await resend.emails.send({
      from: `AFUVAI Ops <${fromEmail}>`,
      to: opsEmail,
      replyTo: clientEmail,
      subject: `NEW INQUIRY${occasionLabel} — ${clientName}`,
      text: opsBody,
    });
  } catch (err) {
    errors.push("ops-email: " + (err.message || err));
    console.error("Ops email send error:", err.message || err);
  }

  if (errors.length) {
    console.error("Errors:", errors.join("; "));
  }

  return { statusCode: 200, body: "OK" };
};
