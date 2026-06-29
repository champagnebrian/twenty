/* ================================================================
   AFUVAI — Snipcart order webhook handler
   Triggered by: order.completed event from Snipcart dashboard
   Webhook URL:  https://afuvai.com/.netlify/functions/order-notify

   Env vars required (set in Netlify UI → Site settings → Env vars):
     RESEND_API_KEY       — from resend.com (free tier: 3k/month)
     OPS_EMAIL            — where ops emails go, default: hello@afuvai.com
     SNIPCART_SECRET_TOKEN — your Snipcart secret API key (for verification)
   ================================================================ */

const { Resend } = require("resend");
const products = require("./data/products.json");

exports.handler = async function (event) {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: "Method Not Allowed" };
  }

  let payload;
  try {
    payload = JSON.parse(event.body);
  } catch {
    return { statusCode: 400, body: "Invalid JSON" };
  }

  // Snipcart sends many event types — only act on completed orders
  if (payload.eventName !== "order.completed") {
    return { statusCode: 200, body: "Ignored" };
  }

  const order = payload.content || {};
  const items = order.items || [];
  const customerName = (order.billingAddress || {}).fullName || "Customer";
  const customerEmail = order.email || "";
  const orderToken = order.token || "unknown";
  const retail = parseFloat(order.total) || 0;

  // Build Bill of Materials across all items
  const flowerMap = {};
  let totalFlowerCost = 0;
  let totalLabor = 0;
  const itemSummaries = [];
  const unknownItems = [];

  for (const item of items) {
    const qty = parseInt(item.quantity) || 1;
    const productData = products[item.id];

    if (!productData) {
      unknownItems.push(`${item.name} × ${qty} (ID: ${item.id} — add to products.json)`);
      continue;
    }

    itemSummaries.push(`  ${productData.name} × ${qty}`);

    for (const ingredient of productData.recipe) {
      const stems = ingredient.stems * qty;
      const cost = stems * ingredient.costPerStem;
      totalFlowerCost += cost;

      if (!flowerMap[ingredient.flower]) {
        flowerMap[ingredient.flower] = { stems: 0, cost: 0, costPerStem: ingredient.costPerStem };
      }
      flowerMap[ingredient.flower].stems += stems;
      flowerMap[ingredient.flower].cost += cost;
    }

    totalLabor += productData.labor * qty;
  }

  const totalCOGS = totalFlowerCost + totalLabor;
  const profit = retail - totalCOGS;
  const marginPct = retail > 0 ? ((profit / retail) * 100).toFixed(1) : "0";

  const BAR = "─".repeat(56);

  const flowerLines = Object.entries(flowerMap).map(([flower, data]) => {
    const name = flower.padEnd(30);
    const stems = `${data.stems} stems`.padEnd(10);
    const cost = `$${data.cost.toFixed(2)}`.padStart(8);
    return `  ${name}${stems}${cost}`;
  });

  const dateStr = new Date().toLocaleDateString("en-US", {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
  });

  const body = [
    `AFUVAI SOCIETY — ORDER OPS BRIEF`,
    BAR,
    ``,
    `Order #   ${orderToken}`,
    `Customer  ${customerName}`,
    `Email     ${customerEmail}`,
    `Date      ${dateStr}`,
    `Retail    $${retail.toFixed(2)}`,
    ``,
    `ITEMS ORDERED`,
    ...itemSummaries,
    ...(unknownItems.length ? [``, `UNKNOWN PRODUCTS (add to products.json):`, ...unknownItems.map(u => `  ⚠  ${u}`)] : []),
    ``,
    BAR,
    `FLOWER BILL OF MATERIALS`,
    BAR,
    ...flowerLines,
    BAR,
    `  Flowers subtotal       $${totalFlowerCost.toFixed(2).padStart(8)}`,
    `  Labor / overhead       $${totalLabor.toFixed(2).padStart(8)}`,
    `  TOTAL COGS             $${totalCOGS.toFixed(2).padStart(8)}`,
    BAR,
    `  NET PROFIT   $${profit.toFixed(2)}   (${marginPct}% margin)`,
    BAR,
    ``,
    `Reply to customer: ${customerEmail}`,
  ].join("\n");

  const subject = `NEW ORDER #${orderToken} — Ops Brief | ${customerName}`;

  const opsEmail = process.env.OPS_EMAIL || "hello@afuvai.com";
  const resend = new Resend(process.env.RESEND_API_KEY);

  try {
    await resend.emails.send({
      from: "AFUVAI Ops <noreply@afuvai.com>",
      to: opsEmail,
      subject,
      text: body,
    });
  } catch (err) {
    // Log but return 200 — prevents Snipcart from retrying indefinitely
    console.error("Resend send error:", err.message || err);
  }

  return { statusCode: 200, body: "OK" };
};
