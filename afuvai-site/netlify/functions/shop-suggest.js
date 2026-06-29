/* ================================================================
   AFUVAI — Shop "Help Me Choose" AI suggestion endpoint
   Called by: shop.html inline script on widget form submit
   Method:    POST  { "question": "..." }
   Returns:   { "suggestion": "..." }

   Env vars required:
     ANTHROPIC_API_KEY  — from console.anthropic.com
   ================================================================ */

const Anthropic = require("@anthropic-ai/sdk");

const PRODUCT_CATALOGUE = `
Available products at AFUVAI Society (Las Vegas florist):

EVERYDAY / GIFT DELIVERY:
- The Garden Pedestal ($185) — lush garden-style roses, sunflowers, eucalyptus in a ceramic bowl
- Desert Bloom ($145) — warm terracotta and amber blooms, greenery, desert-inspired
- Golden Hour ($165) — whites and champagne tones with dusty miller, understated luxury
- Everyday Posy ($95) — petite hand-tied posy, perfect just-because gesture

SYMPATHY / TRIBUTE:
- Heart of Remembrance ($295) — standing heart wreath of garden roses on an easel
- Serene Tribute ($175) — graceful soft whites and greens sympathy arrangement

BESPOKE (by consultation only — not orderable online):
- Weddings (from $3,500), Events (from $1,500), Corporate (by quote)
  → Link: https://afuvai.com/consultation.html
`;

exports.handler = async function (event) {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: "Method Not Allowed" };
  }

  let body;
  try {
    body = JSON.parse(event.body);
  } catch {
    return { statusCode: 400, body: "Invalid JSON" };
  }

  const question = (body.question || "").trim();
  if (!question || question.length < 3) {
    return {
      statusCode: 400,
      body: JSON.stringify({ error: "Please describe what you're looking for." }),
    };
  }

  if (!process.env.ANTHROPIC_API_KEY) {
    return {
      statusCode: 200,
      body: JSON.stringify({ suggestion: "Our shop has arrangements from $95 — browse above or reach out at hello@afuvai.com for personal guidance." }),
    };
  }

  try {
    const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

    const message = await anthropic.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 200,
      messages: [
        {
          role: "user",
          content: `You are the shop assistant for AFUVAI Society, a luxury floral studio in Las Vegas. A customer asked: "${question}"

${PRODUCT_CATALOGUE}

Reply in 2-3 sentences. Recommend one specific product by name and price, explain why it fits their request, and mention they can add a personalisation note at checkout if relevant. If their request is for a wedding, event, or large order, direct them to book a consultation instead. Be warm and helpful, not salesy. Do not use bullet points — write naturally.`,
        },
      ],
    });

    const suggestion = message.content[0].text.trim();

    return {
      statusCode: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ suggestion }),
    };
  } catch (err) {
    console.error("Claude API error:", err.message || err);
    return {
      statusCode: 200,
      body: JSON.stringify({ suggestion: "I'd love to help — please email us at hello@afuvai.com or call (702) 000-0000 for a personal recommendation." }),
    };
  }
};
