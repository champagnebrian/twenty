# AFUVAI — Next.js Migration & Build Handoff

**Prepared:** 2026-07-02 · **Audit model:** Fable 5 · **Status:** planning document only — nothing implemented in this session.
**Audience:** Claude Code sessions (Sonnet 5 default) executing the migration. This doc replaces re-discovery — file paths, component names, and metadata below are taken from the actual code, not summarized.

---

## 0. Read Me First — Context & Corrections

### Where the two codebases actually live

| Codebase | Location | State |
|---|---|---|
| **Live production site** | `champagnebrian/twenty` repo, branch `claude/floral-site-audit-rebuild-kav83p`, folder `afuvai-site/` | Deployed to Netlify site `afuvai-society` (site ID `9227ac22-3eea-4924-a9f0-6275dcefa7f1`), Netlify base directory = `afuvai-site`, publish = `.`, current deploy state: **ready** |
| **Figma v2 source** | `App.tsx` (~2,700-line single-file React/Vite/Tailwind SPA, HashRouter) | Provided as source; not deployed. UI feature-complete, zero persistence, checkout stubbed |

A copy of `afuvai-site/` also exists in Google Drive (`Afuvai Floral/afuvai-site/`), plus a prior handoff doc `AFUVAI_Handoff_v2.md`.

> ⚠️ **Security note:** the Drive doc `AFUVAI_Handoff_v2.md` contains a **Netlify personal access token in plaintext**. Rotate that token before or during this project, and don't paste credentials into docs again. Keys belong in Netlify env vars only.

### Corrections to the brief (verified against code)

1. **The live site is not 7 pages** — it is **11 indexed pages** + 2 redirect stubs + a 404, plus 3 Netlify Functions, `robots.txt`, `sitemap.xml`, and an `llms.txt`. Pages: Home, Shop, Bulk Flowers, Weddings & Events, Classes, Our Story, Consultation, Portfolio, Contact, FAQ, Make a Payment. `about.html` and `services.html` are meta-refresh stubs 301'd (via `netlify.toml`) to `story.html` and `weddings.html`.
2. **The live site's SEO is already strong** — unique `<title>`, meta description, canonical, OG/Twitter tags, and JSON-LD on *every* page; `robots.txt` explicitly allows GPTBot/ClaudeBot/PerplexityBot; there is a hand-written `llms.txt`. This raises the parity bar considerably (full verbatim baseline in §5).
3. **Live commerce is wired but not live**: Snipcart is embedded with placeholder key `YOUR_SNIPCART_PUBLIC_API_KEY` (`shop.html:419`), and class/payment buttons link to `#REPLACE_WITH_STRIPE_LINK` (`classes.html:112,124,136`, `payment.html:84,90`). **Nothing on the live site can take money today.** The Next.js build replaces Snipcart entirely with Stripe.
4. **The live site has an AI ops layer the v2 SPA lacks** (`netlify/functions/`): shop suggestion widget, AI inquiry triage with client + ops emails via Resend, and a Snipcart order webhook that emails a flower bill-of-materials with COGS/margin from `data/products.json`. **These are genuinely valuable and must be ported**, not dropped.
5. **Two different product catalogs exist.** Live: 4 collections × 3 tiers (Classic/Signature/Estate) + Flower Purse + 2 sympathy + ~20 bulk SKUs, each with a COGS recipe in `products.json`. v2: 27 named products (`PRODUCTS` array) with real photos and per-size pricing. v2 is the design source of truth per the brief, but the live catalog's **recipe/COGS system must survive** the migration (it powers the ops email), and the bulk-by-the-stem SKUs exist only on live.
6. **Brand facts conflict** between the sources — founder name ("Ami Nelson" live vs "AmiDayne Nelsen" v2 vs "AmiDayne Nelson" in Drive), contact email (`hello@afuvai.com` live vs `admin@afuvai.com` v2), wedding minimum ($3,500 live vs $1,500 v2), Flower Purse price ($145 live vs $225–385 v2), delivery promise ("order by 1pm for next-day" live vs "order by 2pm for same-day" v2), fonts (Cormorant Garamond/Inter live vs Playfair Display/DM Sans v2), and structural green (`--sage:#23402F` in live `styles.css:13` vs locked `#5A6B54`). All logged in §6 Open Questions — **do not silently pick one during implementation.**

### Confirmed decisions (constraints — do not re-litigate)

Next.js App Router on Netlify · palette locked (sage `#5A6B54` / dark `#3f4e3a`, gold `#B8995A` / light `#d4b578`, ivory `#FAF8F3`, card `#EEEADC`, ink `#1A1A14`, muted `#6B6B58`) · full accounts via Supabase Auth · Stripe Billing auto-charge subscriptions + Customer Portal · no admin dashboard v1 (schema must make it additive) · Mailchimp via Next API route · skip `PurseSpotlight`, fabricated testimonials, and Unsplash imagery.

---

## 1. File Inventory

### 1.1 Live production site — `afuvai-site/` (branch `claude/floral-site-audit-rebuild-kav83p`)

| File | Lines | Purpose | State |
|---|---:|---|---|
| `index.html` | 299 | Home: hero, shop-by-moment, story teaser, portfolio strip, IG grid, testimonials, newsletter | **Working**, but testimonials are literal `"Placeholder testimonial"` text; IG grid is static fallback with a comment to drop in a Behold/EmbedSocial widget |
| `shop.html` | 464 | Shop: 6 occasion filter chips, AI "Help Me Choose" widget, 12 everyday products (4 collections × 3 tiers), Flower Purse, 2 sympathy, 3 consultation cards, Snipcart cart | **Broken checkout** — Snipcart key is placeholder (`:419`); 12 of 15 product images are SVG placeholders (`bouquet-1/2/3/5.svg`); inline suggest-widget script `:423-462` works when `ANTHROPIC_API_KEY` set |
| `bulk.html` | 437 | Bulk flowers: 4 curated DIY kits ($95–$229), ~20 by-the-bunch SKUs ($13–$115), Flower Purse cross-sell, planning CTA | **Broken checkout** (same Snipcart key); content complete |
| `weddings.html` | 173 | Weddings ($3,500+) & events ($1,500+), 4-step process, gallery, single testimonial | Working; testimonial is placeholder; eyebrow text literally says "The High-Value Funnel" (`:52`) — internal jargon leaked into UI, don't port |
| `classes.html` | 263 | Classes & private events, 3 dated workshops (Jul 18 / Aug 02 / Aug 21 — same dates as v2), Host-Your-Own, Flower Purse Party section | **Broken reserve buttons** — `#REPLACE_WITH_STRIPE_LINK` × 3 |
| `story.html` | 141 | Founder story (Ami Nelson), Samoan-motif signature meaning, philosophy | Working; bio and motif copy are marked `Placeholder — refine with Ami's voice` (`:65`, `:81`) |
| `consultation.html` | 156 | Booking page: scheduler embed placeholder + full Netlify Forms inquiry form (name/email/phone/occasion/date/guests/venue/budget/message) | Form markup complete; **scheduler is a placeholder block** (`:62-67`); deposit note is a visible setup note (`:68-70`); ⚠️ Netlify API reports `forms: "not enabled"` for the site — **submissions may be silently lost** |
| `portfolio.html` | 185 | 3 gallery sections (weddings / events / classes) with lightbox | Working; events + classes galleries are mostly `portfolio-e*.svg` / `portfolio-c*.svg` placeholders |
| `contact.html` | 233 | Inquiry form (Netlify Forms, name `contact`) + studio details | Working markup; phone + email labeled `(placeholder)` in the UI (`:159-160`); same forms-not-enabled risk |
| `faq.html` | 165 | 9 `<details>` FAQs mirrored 1:1 in FAQPage JSON-LD | **Working — best page on the site**; states "signature bouquets start around $155" which contradicts shop ($105) |
| `payment.html` | 170 | Deposit / balance / invoice cards → Stripe Payment Links | **Broken** — `#REPLACE_WITH_STRIPE_LINK` × 2; visible "Setup note (remove before launch)" `:100-102` |
| `about.html`, `services.html` | 6 each | Meta-refresh redirect stubs (`noindex,follow`, canonical to target) | Working; duplicated by `netlify.toml` 301s |
| `404.html` | 26 | "This page has wilted." | Working |
| `app.js` | 223 | Shared behavior: mobile nav, IntersectionObserver reveals (motion-safe), inquiry-form validation + Netlify Forms POST, newsletter capture, lightbox, footer year, header shadow, cookie consent (gates GA4/Meta — **loader is a `console.log` placeholder** `:186-189`), shop filter with hash deep-links | Working |
| `styles.css` | 394 | Full design system; tokens at `:root` (`:9-31`) — note `--sage:#23402F` deep forest, `--serif:'Cormorant Garamond'`, `--sans:'Inter'`, extensive AA-contrast annotations | Working |
| `netlify.toml` | 45 | publish `.`, functions dir, 301s for about/services, security headers, cache headers | Working |
| `netlify/functions/shop-suggest.js` | 109 | POST `{question}` → Claude Haiku (`claude-haiku-4-5-20251001`) with inline `PRODUCT_CATALOGUE` → `{suggestion}`; graceful fallbacks | Working when `ANTHROPIC_API_KEY` set; catalog is hardcoded prose that will drift from real products |
| `netlify/functions/inquiry-ai.js` | 159 | Netlify Forms webhook → Claude Haiku drafts client acknowledgment + ops brief → sends both via Resend | Working when env vars set; depends on Netlify Forms webhook (not confirmed configured) |
| `netlify/functions/order-notify.js` | 136 | Snipcart `order.completed` webhook → builds flower BOM + COGS + margin from `data/products.json` → Resend ops email | Logic works; **never fires in production** (Snipcart not configured); `SNIPCART_SECRET_TOKEN` verification is documented but **not implemented** in code |
| `netlify/functions/data/products.json` | 400 | Recipe DB: per-SKU stems, `costPerStem`, labor for 15 shop + 20 bulk SKUs; `_note`: "Fill in your real flower counts and wholesale costs per stem before launch" | Placeholder costs — structure is the valuable part |
| `robots.txt` | 20 | Allow all + explicit allow for GPTBot, OAI-SearchBot, ChatGPT-User, PerplexityBot, ClaudeBot, Claude-Web, Google-Extended; sitemap ref | Working — **must be preserved** |
| `sitemap.xml` | 14 | 11 URLs with changefreq/priority | Working — must be regenerated for new routes |
| `llms.txt` | 39 | GEO summary: brand, service area, offer table with prices, key pages | Working — **must be preserved and kept in sync** |
| `.htaccess` | 28 | Apache leftovers from GoDaddy plan | Dead weight on Netlify — do not port |
| `package.json` | 12 | `@anthropic-ai/sdk`, `resend`, `react`, `react-dom` (peer-dep fix for resend) | Working |
| `yarn.lock` | 0 | Empty file — required hack so Yarn Berry treats `afuvai-site/` as standalone inside the twenty monorepo | Working (see §7 repo recommendation) |
| `assets/` (43 files) | — | `logo.png`, `monogram.png`, `motif-divider.png` (Samoan motif — brand signature, **port these**), `favicon.png/svg`, `og-image.jpg/svg`, 8 real photos in `assets/photos/` (`hero-arch.jpg/webp`, `couple.webp`, `arrangement.webp`, `sympathy.webp`, `bouquet-holder.jpg`, `wedding-couple.jpg`, `wedding-garden-brides.jpg`), ~24 placeholder SVGs (`bouquet-*.svg`, `portfolio-*.svg`, `service-*.svg`, `hero.svg`, etc.) | Photos real; SVGs placeholder |

**Netlify site config (verified via API):** site `afuvai-society`, primary URL `afuvai-society.netlify.app`, no password/SSO gate, forms **not enabled**, current deploy `ready`. Custom-domain DNS (`afuvai.com` on GoDaddy: A `@` → `75.2.60.5`, CNAME `www` → `afuvai-society.netlify.app`) was in progress at the last handoff — **verify it completed** (couldn't be confirmed from this sandbox; see §6).

### 1.2 Figma v2 source — `App.tsx` (~2,700 lines, single file)

All components are defined inside one file; most are nested inside `AppContent` (they close over shared state). Approximate order of appearance:

| Component / block | Purpose | State |
|---|---|---|
| Image imports (26 real PNGs from `@/imports/`) + 6 Unsplash product fallbacks + 17 Unsplash scene constants | Product/portfolio imagery | See photo inventory §1.3 |
| `redirectToStripeCheckout(items)` | Checkout | **Stub** — fires a `toast.error` "coming soon", nothing else |
| Palette/font constants (`SAGE`, `GOLD`, `IVORY`, `CARD`, `INK`, `MUTED`, `serif='Playfair Display'`, `sans='DM Sans'`) | Design tokens | Matches locked palette; fonts differ from live site (§6 Q6) |
| `PRODUCTS` (27 items) | Catalog: id, name, price, category, img, tag, `whiteBg`, `pairedProductId` (purse gold↔black), desc, 3 sizes each | Working data; prices/copy final-looking |
| `ADDONS` (4), `PORTFOLIO_ITEMS` (36) + `PORTFOLIO_CATS`, `TESTIMONIALS` (3, **fabricated — skip**), `SUB_FREQUENCIES` + `SUB_TIERS` (Ivory/Sage/Gold × Weekly/Bi-Weekly/Monthly), `PARTY_EXPERIENCES` (7), `FAQS_PARTIES`/`FAQS_SUB`/`FAQS_WEDDINGS` (5 each), `CLASSES` (4) | Content data | Working; portfolio venues name-drop Bellagio/Wynn/Venetian/Caesars/Four Seasons — **unverified claims, legal risk** (§6 Q9) |
| `SectionHead`, `FaqBlock` | Shared UI | Working |
| `PurseSpotlight` | Purse hero section | **Dead code — defined but never rendered; brief says skip. Do not port** |
| `PAGE_PATHS` / `PATH_PAGES`, `NotFoundPage` | Routing map + 404 | Working (under HashRouter, so URLs are `/#/…` — SEO-invisible) |
| `SchemaInjector` | Injects Florist + FAQPage JSON-LD at runtime via `useEffect` | Works in-browser only; replaced by SSR JSON-LD in Next |
| `AppContent` | ~200 lines of state: `page`, `activeProd`, `cartItems`, `wishlist`, quiz state (lifted), search, meta-tag `useEffect` (one global title/description for all routes) | All `useState`, zero persistence |
| `Nav` (with `DROPDOWN_NAV` mega-menu), `MobileMenu`, `CartDrawer`, `FloatingCTA`, `Footer` | Chrome | Working; `Logo` is text-based ("until real asset is provided" — live site has the real `logo.png`/`monogram.png`) |
| `ProductGrid` | Filter chips + sort + product cards | Working |
| `HomePage` | Hero, trust badges, classes strip, quiz CTA, grid, venue strip, process, weddings band, parties band, testimonials, IG grid, newsletter | Working; newsletter form has **no handler at all** (bare `<input>` + `<button>`); stats "1,200+ events / 6+ years / 4.9★" unverified |
| `ProductPage` | Size selector, **Subscribe & Save 15% vs one-time** toggle, frequency picker, delivery date + zip validation (89xxx length only), gift note, 4 add-ons, paired purse chain switcher, related + palette-based "You may also love" (`PALETTE_TAGS` map) | Working UI; all client state; `/product` route renders from `activeProd` state → **deep links and refreshes lose the product** (falls back to HomePage) |
| `PortfolioPage` | 36 items, category filter, `PORTFOLIO_PRODUCT_MAP` linking portfolio → product pages ("Shop This") | Working |
| `WeddingsPage` | Hero, `AvailabilityChecker`, process strip, 6 services, `ConsultationBooking`, inquiry form, FAQ | Forms fire `toast.success` only — **no submission backend** |
| `PartiesPage` | Hero, `ConsultationBooking`, 7 experiences, FAQ, inquiry form, contact band | Same — toast only |
| `SubscriptionsPage` | Frequency toggle + 3 tier cards + FAQ | **Bug:** `useState("Atelier")` default tier doesn't exist in `SUB_TIERS` (Ivory/Sage/Gold) → no card selected and the subscribe button renders "Subscribe — undefined · $undefined" until a tier is clicked. Subscribe button itself has no handler |
| `ClassesPage` | 4 class types, 3 dated workshops with real Google-Calendar "Add to Calendar" links, reserve buttons (no handler), booking form (toast only) | Working UI |
| `BulkPage` | 5 packages (`BULK_PACKAGES`, ids 2001–2005) + `GREENERY_ADDON` (2099) added to cart via synthetic products, custom inquiry form | Working UI; note live site's per-stem SKUs are richer |
| `FloristPage` | AmiDayne bio + story | Working; copy conflicts with live `story.html` (§6 Q1) |
| `CollabsPage` | 6 partnership formats + pitch form | Working UI, toast-only submit |
| `CarePage` | 6-step care guide + founder note | Working |
| `GiftCardsPage` | Amount presets + custom, recipient form, live-preview card, add-to-cart (synthetic product id `9001+amount`) | Working UI; no real gift-card issuance |
| `QuizPage` | 3-step (occasion → palette → budget) with custom SVG icons, `PALETTE_PRODUCTS` + `budgetFilter` matching, results grid with fallback | Working |
| `AvailabilityChecker` | Date input → `setTimeout` fake check (Fridays = "limited") | **Fake** — flagged in brief as open question |
| `ConsultationBooking` | 14-day picker, 7 time slots, fake `bookedSlots`, details form, confirmation state | **Fake backend** — no persistence, no calendar |
| `AccountPage` | 6 tabs (Overview / Orders / Subscription / Reminders / Addresses / Preferences) with `MOCK_ORDERS`, `CURRENT_SUB`, mock profile "Jane Smith" | Complete UI mockup; 100% mock data — this is the UI target for Supabase wiring |
| Render root + `<style>` block | Routes, Toaster, marquee/fade keyframes, mobile fixes | Working |

Other v2 issues to fix on the way in: `wishlist` state + `toggleWishlist` exist but no UI ever calls or displays them (dead until Accounts phase); cart `id` collisions possible between synthetic bulk/gift-card ids and future real ids; extensive `(product as any).whiteBg` casts (type properly in Next); all meta is one global title/description regardless of route.

### 1.3 v2 photo inventory — real vs placeholder

**26 real product/brand photos** (files in `@/imports/`, PNG): `imgPurse`, `imgPurseBlack`, `imgPurseLifestyle` (IMG_4773.PNG), `imgGoldenHour`, `imgVividFiesta`, `imgStatement`, `imgJewelGarden`, `imgWildMeadow`, `imgVioletReverie`, `imgGardenOfPeace`, `imgHarvestBasket`, `amiDayneImg` (founder portrait), `imgKaleidoscope`, `imgGardenSunrise`, `imgBlushingGarden`, `imgMetalArch`, `imgGardenReverie`, `imgCrimsonAffair`, `imgBloomBox`, `imgIvoryReverie`, `imgGardenBliss`, `imgLavenderDreams`, `imgPrimaryBurst`, `imgTropicalBox`, `imgHexArch`, `imgParadiseBox`.

**Products still on Unsplash placeholders (6 of 27):** id 3 Summer Radiance, id 9 Heart of Remembrance, id 12 Blush Reverie, id 13 Festival Bloom, id 14 Pure Serenity, id 15 Golden Harvest. → Real photos needed or shoot list for Ami.

**Scene/section imagery entirely Unsplash (17 constants):** `HERO_IMG`, `STUDIO_IMG`, `ROSE_IMG`, `WHITE_FLORAL`, `PINK_BOUQUET`, `PURPLE_BOUQUET`, `MIXED_VASE`, `GARDEN_MIX`, `PETAL_MACRO`, `ORCHID_DARK`, `FLOWER_CLOSEUP`, `WEDDING_ARCH`, `WEDDING_BRIDE`, `WEDDING_DECOR`, `RECEPTION_TABLE`, `PARTY_IMG`, `WORKSHOP_IMG`. These feed the home hero, weddings/parties/classes/bulk heroes, and all 4 `ADDONS` images. **Per the brief these must be replaced.** Real candidates that exist: live-site `assets/photos/hero-arch.webp` (hero), `couple.webp`, `wedding-couple.jpg`, `wedding-garden-brides.jpg` (weddings), `arrangement.webp`, `sympathy.webp`, `bouquet-holder.jpg` (purse). Remaining gaps → photo shoot list (§8).

---

## 2. Migration Map — v2 component → Next.js target

Proposed app skeleton (new project — see §7 for repo placement):

```
afuvai-next/
  app/
    layout.tsx            ← Nav, Footer, Toaster, fonts, global JSON-LD (Florist + WebSite)
    page.tsx              ← HomePage
    shop/page.tsx         ← ProductGrid + filters (replaces v2 home-embedded grid AND live shop.html)
    shop/[slug]/page.tsx  ← ProductPage (dynamic, SSG per product)
    portfolio/page.tsx
    weddings/page.tsx
    parties/page.tsx
    subscriptions/page.tsx
    classes/page.tsx
    bulk/page.tsx
    collabs/page.tsx
    story/page.tsx        ← FloristPage (URL matches live story.html for SEO continuity)
    care/page.tsx
    gift-cards/page.tsx
    quiz/page.tsx
    faq/page.tsx          ← NEW page (exists on live, missing in v2)
    contact/page.tsx      ← NEW page (exists on live, missing in v2)
    payment/page.tsx      ← Make-a-Payment (exists on live, missing in v2)
    consultation/page.tsx ← ConsultationBooking promoted to its own route (matches live)
    account/…             ← (auth) group: overview/orders/subscription/reminders/addresses/preferences
    login/page.tsx
    api/…                 ← route handlers (checkout, webhooks, newsletter, suggest, inquiry, availability)
    sitemap.ts, robots.ts, not-found.tsx
  components/ · lib/ (supabase, stripe, resend, mailchimp clients) · content/ (products.ts, classes.ts, faqs.ts) · public/ (photos, logo, monogram, motif, llms.txt)
```

| v2 source (in `App.tsx`) | Next.js target | What changes on the way in |
|---|---|---|
| `HashRouter` + `PAGE_PATHS`/`navigate()` | File-based routes; `<Link>`; delete `PATH_PAGES`, `pageFromPath`, popstate sync | Real URLs; scroll behavior via Next defaults + `goToSection` → anchor links |
| Global meta `useEffect` + `SchemaInjector` | `export const metadata` per page + `<script type="application/ld+json">` rendered server-side per route | **Non-negotiable per-page task — see §5 table for exact targets** |
| `PRODUCTS`, `ADDONS`, `SUB_TIERS`, `CLASSES`, `PARTY_EXPERIENCES`, FAQ arrays | `content/*.ts` initially → Supabase `products` et al. tables in the backend phase (needed for admin-later + recipes) | Add `slug`, merge live catalog's recipe/COGS fields; **reconcile the two catalogs** (§6 Q3) |
| `Nav`, `MobileMenu`, `Footer`, `FloatingCTA` | `components/` client components in `layout.tsx` | Use real `logo.png` + `monogram.png` from live assets; add `/faq`, `/contact` links; cart count from persisted cart |
| `ProductGrid` + occasion chips + sort | `app/shop/page.tsx` (+ home teaser grid) | Filter/sort as `searchParams` so filtered views are linkable |
| `ProductPage` (incl. paired-purse switcher, add-ons, zip check, gift note, subscribe toggle) | `app/shop/[slug]/page.tsx` — `generateStaticParams` over all products | Per-product **Product JSON-LD + OG image** (the single biggest SEO upgrade available); `activeProd` state → route param; cart via context + `localStorage`; real zip validation against delivery-area list |
| `CartDrawer` + `redirectToStripeCheckout` | `components/cart-drawer.tsx` + `app/api/checkout/route.ts` → Stripe Checkout Session | The stub becomes real (§4) |
| `PortfolioPage` + `PORTFOLIO_PRODUCT_MAP` | `app/portfolio/page.tsx` | Keep Shop-This links as `<Link href={/shop/[slug]}>`; **strip unverified venue names** pending §6 Q9 |
| `WeddingsPage` / `PartiesPage` / `CollabsPage` / `ClassesPage` / `BulkPage` forms | Server actions or `app/api/inquiry/route.ts` | Replace toast-only submits with real submission → Supabase `inquiries` table + port `inquiry-ai.js` triage (Claude + Resend) |
| `ConsultationBooking`, `AvailabilityChecker` | `app/consultation/page.tsx` + `app/api/availability/route.ts` | v1: keep the picker UI but persist bookings to Supabase + email Ami (no fake `setTimeout`); real calendar backend is §6 Q10 |
| `SubscriptionsPage` | `app/subscriptions/page.tsx` | **Fix the `"Atelier"` default-tier bug** (init to `"Sage"`); subscribe button → Stripe Checkout in subscription mode (§4.2) |
| `QuizPage` (+ lifted quiz state) | `app/quiz/page.tsx` client component | State stays local (fine); results link to `/shop/[slug]` |
| `GiftCardsPage` | `app/gift-cards/page.tsx` | Back with Stripe (§4.2 gift cards) instead of synthetic cart product |
| `AccountPage` (6 tabs, all mock) | `app/account/*` behind Supabase Auth | `MOCK_ORDERS` → `orders` query; `CURRENT_SUB` → `subscriptions` + Stripe Customer Portal link; reminders/addresses/preferences → tables (§4.1) |
| `FloristPage` | `app/story/page.tsx` | Merge with live `story.html` copy + AboutPage/Person JSON-LD; resolve founder-name conflict first |
| `CarePage` | `app/care/page.tsx` | Straight port; add HowTo JSON-LD (optional nice-to-have) |
| Home newsletter `<input>` (no handler) + live `data-newsletter` forms | `components/newsletter-form.tsx` → `app/api/newsletter/route.ts` → Mailchimp Marketing API (`lists/{listId}/members`, status `pending` for double-opt-in) | Confirmed decision; replaces both the dead v2 form and live Netlify-Forms capture |
| `PurseSpotlight`, `TESTIMONIALS`, Unsplash constants | **Not ported** | Per brief |
| — (live only) `faq.html` | `app/faq/page.tsx` | Port the 9 Q&As + FAQPage JSON-LD verbatim; merge v2's context FAQ arrays into page sections |
| — (live only) `contact.html`, `payment.html` | `app/contact/page.tsx`, `app/payment/page.tsx` | Payment page: real Stripe Payment Links (deposit/balance) or embedded custom-amount checkout |
| — (live only) `shop-suggest.js` | `app/api/suggest/route.ts` | Build `PRODUCT_CATALOGUE` string from the products table at request time instead of hardcoded prose |
| — (live only) `inquiry-ai.js` | `app/api/inquiry/route.ts` | Trigger directly from form submission (no Netlify Forms webhook dependency) |
| — (live only) `order-notify.js` + `data/products.json` | Stripe webhook handler (§4.3) reuses the BOM/COGS logic; recipes move into `products` table | Snipcart payload parsing → Stripe `checkout.session.completed` line items |
| — (live only) `robots.txt`, `llms.txt`, `sitemap.xml`, `motif-divider.png`, security headers | `app/robots.ts` (keep AI-crawler allows), `public/llms.txt` (updated), `app/sitemap.ts`, motif as brand element, headers in `netlify.toml` | Preserve — these are live SEO/GEO assets |

**URL redirect map (must ship with the first deploy):** `/index.html→/`, `/shop.html→/shop`, `/bulk.html→/bulk`, `/weddings.html→/weddings`, `/classes.html→/classes`, `/story.html→/story`, `/consultation.html→/consultation`, `/portfolio.html→/portfolio`, `/contact.html→/contact`, `/faq.html→/faq`, `/payment.html→/payment`, `/about.html→/story`, `/services.html→/weddings` — all 301, in `netlify.toml` or `next.config.js` `redirects()`.

---

## 3. Task List

Model key: **S** = Sonnet 5 (default) · **O** = Opus 4.8 (escalate only if flagged) · **F** = Fable 5 (only where flagged). "Session" = one focused Claude Code session.

### Phase A — Foundation

| # | Task | Source → Target | Model | Sessions | Depends on |
|---|---|---|---|---:|---|
| A1 | Scaffold Next.js 15 App Router project (TS, Tailwind, shadcn/ui), port design tokens (locked palette, decide fonts per §6 Q6), global `layout.tsx` with Nav/Footer/Toaster | v2 constants + `Nav`/`Footer` → `app/layout.tsx`, `tailwind.config`, `components/` | S | 1 | — |
| A2 | Extract all v2 data arrays into typed `content/*.ts`; add slugs; merge live-catalog recipe fields from `netlify/functions/data/products.json`; copy 26 real photos into `public/photos/` with descriptive kebab-case names (`the-afuvai-purse-gold.png` not `192548D1-….PNG`) | `App.tsx` data + `products.json` → `content/`, `public/` | S | 1 | A1 |
| A3 | Home page port (skip PurseSpotlight/testimonials/Unsplash; use `hero-arch.webp` hero) with full metadata + Florist/WebSite JSON-LD | `HomePage` → `app/page.tsx` | S | 1 | A1, A2 |
| A4 | Shop grid + product detail pages with `generateStaticParams`, per-product `generateMetadata` + Product JSON-LD, paired-purse switcher, add-ons, zip validation | `ProductGrid`, `ProductPage` → `app/shop/…` | S (flag O if cart context gets hairy) | 2 | A2 |
| A5 | Cart context + drawer with `localStorage` persistence | `CartDrawer`, cart state → `components/cart/` | S | 1 | A4 |
| A6 | Static content pages: portfolio, story, care, faq, contact, quiz — each with own metadata + JSON-LD (AboutPage/Person, FAQPage, ContactPage, CollectionPage) | `PortfolioPage`/`FloristPage`/`CarePage`/`QuizPage` + live `faq.html`/`contact.html` | S | 2 | A1–A3 |
| A7 | Weddings, parties, classes, bulk, collabs pages incl. inquiry forms posting to `/api/inquiry` (stub OK until B4) | respective v2 pages | S | 2 | A1–A3 |
| A8 | Redirect map, `app/robots.ts` (AI crawlers), `app/sitemap.ts`, `public/llms.txt` update, security/cache headers, 404 page | live `netlify.toml`/`robots.txt`/`llms.txt`/`404.html` | S | 1 | A3–A7 |
| A9 | SEO parity audit pass — run §5 table page-by-page against the built site; fix gaps; Lighthouse ≥ 95 SEO/a11y | — | S | 1 | A8 |

### Phase B — Backend (expensive to get wrong)

| # | Task | Model | Sessions | Depends on |
|---|---|---|---:|---|
| B1 | **Supabase project + schema + RLS** exactly per §4.1 (migrations checked into repo), seed products from `content/` | **F** | 1 | A2 |
| B2 | **Supabase Auth (magic link per §4.4)** — login page, middleware-protected `/account`, profile bootstrap trigger | **F** (design) then S (UI polish) | 1–2 | B1 |
| B3 | **Stripe setup + one-time checkout**: products/prices sync script (`scripts/stripe-sync.ts`), `/api/checkout` (Checkout Session, shipping address collection, delivery-date/gift-note as metadata), success/cancel pages | **F** (architecture) | 1 | B1 |
| B4 | **Stripe webhook handler** `/api/stripe/webhook` per §4.3: signature verify, idempotency, order + BOM/COGS ops email (port `order-notify.js` logic), Resend receipts | **F** | 1 | B3 |
| B5 | **Stripe Billing subscriptions**: 3 products × 3 interval prices per §4.2, subscriptions page wiring (fix `"Atelier"` bug), Customer Portal config + deep link from account | **F** | 1–2 | B3, B4 |
| B6 | Account pages on real data: orders list, subscription card, addresses CRUD, reminders CRUD (+ scheduled reminder emails via Supabase cron + Resend), preferences | S (O if the reminder scheduler gets complex) | 2 | B2, B4, B5 |
| B7 | Inquiry pipeline: `/api/inquiry` → `inquiries` table + port `inquiry-ai.js` (Claude Haiku triage → Resend client-ack + ops brief) | S | 1 | B1 |
| B8 | Newsletter: `/api/newsletter` → Mailchimp API (custom-styled form, double opt-in, error states) | S | 0.5 | A1 |
| B9 | Shop-suggest AI: `/api/suggest` building catalog from DB | S | 0.5 | B1 |
| B10 | Consultation booking v1: persist `consultation_requests`, availability endpoint (real rules, not `setTimeout`), ops email | S | 1 | B1, B7 |
| B11 | Gift cards via Stripe (§4.2) + delivery email w/ code, redemption at checkout | S (flag O — coupon/ledger edge cases) | 1–2 | B3, B4 |
| B12 | Class reservations: Stripe Payment Links or Checkout per dated workshop, seat counts in `classes` table, decrement on webhook | S | 1 | B4 |
| B13 | Payment page: deposit/balance Payment Links + custom-amount invoice flow | S | 0.5 | B3 |

### Phase C — Launch

| # | Task | Model | Sessions | Depends on |
|---|---|---|---:|---|
| C1 | Netlify cutover: new site (or repointed base dir) for Next runtime, env vars (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `MAILCHIMP_API_KEY`+`LIST_ID`, `OPS_EMAIL`, `FROM_EMAIL`), domain + SSL verification, redirect smoke test | S | 1 | A9, B4 |
| C2 | Analytics: GA4 + consent banner (port live cookie-consent, actually load GA4 on accept — live's loader is a placeholder), conversion events (add-to-cart, checkout, subscribe, inquiry) | S | 0.5 | C1 |
| C3 | E2E pass: purchase, subscribe, cancel via portal, failed-payment path (Stripe test clocks), account flows, forms; mobile QA | S | 1 | all B |
| C4 | Content finalization with Brian/Ami: real phone, founder-name spelling, bio, motif meaning, real testimonials, photo shoot gaps (§8) | human + S | 1 | — |

**Total: ~24–28 sessions** (≈17 Sonnet, ≈5–6 Fable, 0–3 Opus escalations).

---

## 4. Backend Architecture (opinionated)

### 4.1 Supabase schema

Principles: Stripe is the source of truth for money; Supabase mirrors it for display + ops. Every table gets RLS. Admin dashboard later = **new client on the same tables + an `is_admin` flag**, zero restructuring.

```sql
-- profiles: 1:1 with auth.users (created by trigger on signup)
create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  full_name text,
  phone text,
  stripe_customer_id text unique,          -- set lazily on first checkout
  default_address_id uuid,
  palette_preference text,                 -- 'romantic' | 'vibrant' | ...
  notif_email boolean not null default true,
  notif_sms boolean not null default false,
  is_admin boolean not null default false, -- future dashboard gate
  created_at timestamptz not null default now()
);

create table addresses (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references profiles(id) on delete cascade,
  label text not null default 'Home',
  recipient_name text,
  line1 text not null, line2 text,
  city text not null default 'Las Vegas',
  state text not null default 'NV',
  zip text not null,
  is_default boolean not null default false,
  created_at timestamptz not null default now()
);

-- products: catalog + recipe/COGS (replaces content/*.ts AND live products.json)
create table products (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,               -- 'the-afuvai-purse-gold-chain'
  name text not null,
  description text,
  category text not null,                  -- 'Signature'|'Wedding'|...|'Bulk'|'GiftCard'|'Class'
  tag text, image_path text, white_bg boolean default false,
  paired_product_id uuid references products(id),
  palette_tag text,                        -- quiz/similar matching
  active boolean not null default true,
  sort_order int,
  created_at timestamptz not null default now()
);

create table product_variants (            -- sizes: Mini/Classic/Grand etc.
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references products(id) on delete cascade,
  label text not null,
  price_cents int not null,
  stripe_price_id text,                    -- one-time Price
  stripe_sub_price_ids jsonb,              -- optional {weekly,biweekly,monthly} if per-product subs ship
  recipe jsonb,                            -- [{flower, stems, cost_per_stem_cents}] — ports products.json
  labor_cents int default 0,
  unique (product_id, label)
);

create table orders (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid references profiles(id),          -- nullable: guest checkout
  email text not null,
  stripe_checkout_session_id text unique,
  stripe_payment_intent_id text unique,
  status text not null default 'paid',              -- paid|preparing|delivered|refunded|canceled
  subtotal_cents int not null, total_cents int not null,
  delivery_date date, delivery_zip text, gift_note text,
  shipping_address jsonb,                            -- snapshot, never a FK
  source text not null default 'shop',               -- shop|subscription|gift_card|class|invoice
  created_at timestamptz not null default now()
);

create table order_items (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references orders(id) on delete cascade,
  product_id uuid references products(id),
  variant_label text, name text not null,             -- snapshots
  qty int not null default 1, unit_price_cents int not null,
  addons jsonb
);

create table subscriptions (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references profiles(id),
  stripe_subscription_id text unique not null,
  tier text not null,                                  -- 'ivory'|'sage'|'gold'
  frequency text not null,                             -- 'weekly'|'biweekly'|'monthly'
  status text not null,                                -- mirrors Stripe verbatim
  current_period_end timestamptz,
  cancel_at_period_end boolean default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table reminders (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references profiles(id) on delete cascade,
  name text not null, occasion text not null,
  event_date date not null,
  advance_days int not null default 14,
  active boolean not null default true,
  last_sent_at timestamptz
);

create table inquiries (                                -- weddings/parties/classes/bulk/collabs/contact
  id uuid primary key default gen_random_uuid(),
  kind text not null,
  name text not null, email text not null, phone text,
  event_date date, guests text, venue text, budget text,
  payload jsonb not null,                               -- full form snapshot
  ai_brief text,                                        -- from inquiry triage
  status text not null default 'new',                   -- new|responded|booked|closed  ← admin-ready
  created_at timestamptz not null default now()
);

create table consultation_requests (
  id uuid primary key default gen_random_uuid(),
  inquiry_id uuid references inquiries(id),
  requested_at timestamptz not null,                    -- chosen slot
  status text not null default 'requested'              -- requested|confirmed|completed|canceled
);

create table gift_cards (
  id uuid primary key default gen_random_uuid(),
  code text unique not null,
  stripe_coupon_id text,                                -- or promotion_code id
  initial_cents int not null, balance_cents int not null,
  purchaser_email text, recipient_email text, recipient_name text,
  message text, send_on date, sent_at timestamptz,
  order_id uuid references orders(id),
  created_at timestamptz not null default now()
);

create table classes (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null, name text not null,
  starts_at timestamptz not null, duration_minutes int,
  price_cents int not null, seats_total int not null, seats_taken int not null default 0,
  stripe_price_id text, active boolean default true
);

create table stripe_events (                            -- webhook idempotency ledger
  id text primary key,                                  -- Stripe event id
  type text not null, processed_at timestamptz not null default now()
);
```

**RLS sketch:** `profiles/addresses/reminders`: `auth.uid() = profile_id` (or `= id`) for all ops. `orders/order_items/subscriptions`: select where owner; **insert/update only via service role** (webhooks). `products/classes`: public select where `active`; write service-role only. `inquiries/consultation_requests/gift_cards/stripe_events`: service-role only (owner-select on gift cards by recipient email optional later). Admin dashboard later: policies `using (is_admin(auth.uid()))` added alongside — additive, no migration of data.

**What an admin dashboard needs later (do NOT build now):** `is_admin` flag (exists), `orders.status` transitions (exists), `inquiries.status` (exists), a `/admin` route group querying the same tables, and optionally an `audit_log` table. Nothing structural.

### 4.2 Stripe setup

**Subscription tiers — 3 Products × 3 recurring Prices each (9 total):**

| Product | Weekly | Bi-Weekly (`interval=week, interval_count=2`) | Monthly |
|---|---:|---:|---:|
| AFUVAI Ivory Subscription | $65 | $55 | $45 |
| AFUVAI Sage Subscription | $135 | $115 | $90 |
| AFUVAI Gold Subscription | $280 | $240 | $195 |

(Prices from v2 `SUB_TIERS`; lock with Ami before creating — §6 Q4.) Use `lookup_key`s like `sub_sage_biweekly` so code never hardcodes price IDs. Checkout: `mode: 'subscription'`, `allow_promotion_codes: true`, collect shipping address. Plan changes/cancel/pause: **Stripe Customer Portal** (configure: allow switching among the 9 prices with proration disabled, cancellation at period end, pause up to 2 cycles). The account page's Skip-Next button = one-cycle pause via API, or defer to portal in v1.

**One-time catalog:** one Stripe Product per catalog product, one Price per size variant, created by `scripts/stripe-sync.ts` reading the `products`/`product_variants` tables (idempotent by `lookup_key = slug + variant`). Add-ons are their own Prices. Delivery date, zip, gift note → Checkout Session `metadata` (webhook copies to `orders`).

**Per-product "Subscribe & Save 15%" (v2 `ProductPage` toggle):** honest recommendation — **defer to v2.1**. Done properly it's 27 products × 3 sizes × 3 frequencies = 243 recurring Prices plus per-item fulfillment logic. Tier subscriptions cover the recurring-revenue goal at 9 Prices. Keep the toggle UI but have "Subscribe & Save" route to the tier page in v1, or hide it.

**Gift cards:** sell as a one-time Price (custom amounts via `price_data`); webhook issues a row in `gift_cards` + a Stripe Promotion Code of equal value, emailed via Resend on `send_on`. (Stripe has no native gift-card balance product; the coupon-ledger approach is standard. Partial-redemption tracking = decrement `balance_cents` and reissue a code, or restrict v1 to single-use full-value codes — flag in UI.)

**Classes:** simplest robust v1 = Stripe Payment Link per dated workshop (quantity-limited in Stripe), plus webhook decrements `classes.seats_taken`. This matches what the live site already scaffolded (`classes.html` reserve buttons).

**Deposits/invoices (payment page):** two Payment Links (deposit = open amount, balance = open amount) + Stripe Invoicing for per-client amounts. No code beyond linking.

**Account access:** Stripe account is under Ami's business; Brian added as team member (Developer role for keys + webhooks). Use restricted keys in Netlify env.

### 4.3 Webhook flow — Stripe → Supabase

Single endpoint `app/api/stripe/webhook/route.ts` (Node runtime, raw body for signature verify):

```
checkout.session.completed
  → idempotency check (insert stripe_events, bail if exists)
  → mode=payment: upsert orders + order_items (expand line_items),
      link profile by customer email if exists, copy metadata (delivery_date, zip, gift_note)
      → if gift-card line: create gift_cards row + schedule delivery email
      → if class line: increment classes.seats_taken
      → BOM/COGS ops email to OPS_EMAIL (port of order-notify.js: recipe from product_variants.recipe,
        flower map, stems, cost, labor, margin — keep the exact text format, Ami's team already knows it)
      → customer receipt email (Resend) — Stripe's receipt also on
  → mode=subscription: create subscriptions row (tier/frequency from price lookup_key)

customer.subscription.created|updated|deleted
  → upsert subscriptions (status, current_period_end, cancel_at_period_end verbatim from Stripe)

invoice.paid (subscription cycles)
  → create orders row (source='subscription') → ops email "subscription delivery due" with tier BOM

invoice.payment_failed
  → mark subscriptions.status='past_due', ops alert email; Stripe Smart Retries + dunning emails ON
    (Billing → revenue recovery); Customer Portal lets the customer fix their card

charge.refunded → orders.status='refunded'
```

Rules: verify `stripe-signature` with `STRIPE_WEBHOOK_SECRET`; always 200 after recording the event (retry storms otherwise); all DB writes via `SUPABASE_SERVICE_ROLE_KEY` server-side only; never trust client-posted prices — line items come from Stripe.

### 4.4 Auth recommendation: **magic link primary, no passwords in v1**

Justification:
1. **Purchase-frequency profile.** Florist customers buy a few times a year. Passwords for rarely-used accounts = guaranteed reset flows, which are just worse magic links. Magic link makes every login the happy path.
2. **Guest-to-account continuity.** Stripe Checkout runs on email. After a guest purchase, "enter your email to see your order" magic-links straight into an account whose `orders` rows are already linked by email match — no password-creation wall at the highest-value moment.
3. **Less to build and secure.** No reset flow, no strength meter, no credential-stuffing surface. Supabase OTP email is one call (`signInWithOtp`).
4. **Deliverability is the one real risk** — mitigate by sending auth mail through the same verified domain used for receipts (Resend/custom SMTP on `afuvai.com`, already required for order email anyway), and show a 6-digit OTP code fallback (Supabase supports both in the same email) for users whose mail client mangles links.
5. **Additive later:** Google OAuth (one toggle) for repeat customers; passwords can be enabled later without migration since Supabase users are email-keyed.

Sessions via `@supabase/ssr` cookie helpers; `/account/*` gated in `middleware.ts`.

---

## 5. SEO / GEO Parity Check

### 5.1 Verbatim baseline (live) → Next.js target

Every page below is an **explicit migration task**, not a side effect. Titles/descriptions are quoted exactly from the live HTML `<head>`.

| Live page | Live `<title>` (verbatim) | Live meta description (verbatim) | Live JSON-LD | Next route → required metadata |
|---|---|---|---|---|
| `/` | `AFUVAI Society \| Luxury Floral Design in Las Vegas` | `AFUVAI Society is a by-appointment luxury floral studio in Las Vegas — bespoke weddings & events, everyday and sympathy arrangements, floral-making classes, and signature bouquets delivered across the valley.` | `Florist` (`@id: https://afuvai.com/#business`, areaServed LV/Summerlin/Henderson/NLV/Strip, `makesOffer` ×3 with minPrices, openingHours, sameAs IG/TikTok/Pinterest) + `WebSite` | `/` — keep or improve both verbatim; Florist JSON-LD in `layout.tsx`, upgraded with `geo`, real `telephone`, and (once reviews exist) `aggregateRating` |
| `/shop.html` | `Shop Flowers by Occasion \| AFUVAI Society Las Vegas` | `Order AFUVAI Society flowers online — everyday arrangements, sympathy tributes, and signature bouquets delivered across the Las Vegas valley. Weddings, events & corporate by consultation.` | `CollectionPage` | `/shop` + `ItemList`; **plus 27 new `/shop/[slug]` pages each with `Product` JSON-LD (name, image, description, offers with price/availability, brand)** — net-new surface area the live site doesn't have; largest ranking lever in this migration |
| `/bulk.html` | `Bulk Flowers Las Vegas \| AFUVAI Society` | `Buy fresh flowers in bulk for weddings, events, and DIY arrangements in Las Vegas. Studio-quality blooms, curated bundles, and by-the-bunch ordering with same-valley delivery.` | `CollectionPage` | `/bulk` — same + Product schema for kits ("bulk flowers las vegas" is a real commercial query; live page is well-optimized, don't regress) |
| `/weddings.html` | `Wedding & Event Florals in Las Vegas \| AFUVAI Society` | `Bespoke wedding and event floral design in Las Vegas — bridal bouquets, ceremony arches, reception installations, galas and corporate florals. By appointment.` | `Service` (minPrice 1500) | `/weddings` — keep `Service`; resolve $1,500 vs $3,500 (§6 Q5) before writing the offer price into schema |
| `/classes.html` | `Floral-Making Classes & Private Events in Las Vegas \| AFUVAI` | `Book a hands-on floral-making class in Las Vegas, or host your own private floral event — bridal showers, team building, celebrations. Seats from $125. All blooms & tools included.` | `Course` + `CourseInstance` (Onsite, LV) | `/classes` — keep Course; add per-workshop `Event` schema with dates (rich-result eligible) |
| `/story.html` | `Our Story \| AFUVAI Society — Las Vegas Floral Designer` | `Meet AFUVAI Society — a Las Vegas luxury floral studio founded by Ami Nelson, built on heritage, hospitality, and a Samoan-motif signature.` | `AboutPage` + `Person` (Ami Nelson, Founder & Lead Floral Designer) | `/story` — keep; founder name must be resolved first (§6 Q1) |
| `/consultation.html` | `Book a Consultation \| AFUVAI Society Las Vegas` | `Book a floral design consultation with AFUVAI Society in Las Vegas — weddings, events, and bespoke work. Choose a time or send your details.` | `WebPage` | `/consultation` — keep |
| `/portfolio.html` | `Portfolio \| AFUVAI Las Vegas Floral Design` | `Explore AFUVAI's portfolio of luxury Las Vegas floral design — weddings, private and corporate events, and floral-making classes. Custom floral artistry, by appointment.` | `CollectionPage` | `/portfolio` — keep; add `ImageObject`s once real photos land |
| `/contact.html` | `Contact & Inquire \| AFUVAI Las Vegas Luxury Florist` | `Inquire about bespoke wedding, event, class, or custom floral design with AFUVAI in Las Vegas. By appointment. Send an inquiry — we respond within one business day.` | `ContactPage` + `Florist` entity | `/contact` — keep |
| `/faq.html` | `FAQ \| AFUVAI Las Vegas Luxury Floral Studio` | `Answers about AFUVAI — pricing minimums, service area, booking lead time, online bouquet orders, floral classes, delivery, and how our by-appointment Las Vegas floral studio works.` | **`FAQPage` with 9 Question/Answer pairs matching visible content 1:1** | `/faq` — port verbatim (this is the site's best GEO asset — AI engines quote FAQ content heavily); fix the "$155" price inconsistency; **v2 has no FAQ page — flagged as new-build** |
| `/payment.html` | `Make a Payment \| AFUVAI Las Vegas Floral Studio` | `Securely pay your AFUVAI deposit, balance, or custom invoice. Payments are processed through Stripe. For clients with an active proposal or quote.` | `WebPage` | `/payment` — keep |
| all pages | — | — | canonical, `robots: index,follow,max-image-preview:large`, full OG (`og:site_name`, type, title, desc, url, image) + `twitter:card summary_large_image`, `theme-color #5A6B54` | replicate via Metadata API defaults in `layout.tsx` + per-page overrides; generate per-page OG images (product photo for product pages) instead of the single shared `og-image.jpg` |
| `robots.txt` | — | explicit Allow for GPTBot, OAI-SearchBot, ChatGPT-User, PerplexityBot, ClaudeBot, Claude-Web, Google-Extended + sitemap | `app/robots.ts` — **preserve the AI-crawler section exactly** |
| `llms.txt` | — | brand summary, service area, full offer/price list, key pages | `public/llms.txt` — update prices/URLs to new routes; add subscriptions section when live |
| `sitemap.xml` | — | 11 URLs, priorities | `app/sitemap.ts` — all pages + 27 product URLs + class pages |

### 5.2 Regression risks — flag BEFORE they happen

1. **URL scheme change** (`*.html` → clean routes) forfeits existing indexing unless the §2 redirect map ships in the same deploy as the new site. This is the #1 way this migration loses rankings. Test every one of the 13 redirects post-deploy.
2. **v2's runtime meta injection must not survive the port.** `SchemaInjector` and the `document.title` `useEffect` are client-side; if any page ships relying on them, crawlers see nothing. Every route: `export const metadata` / `generateMetadata` server-side. No exceptions.
3. **v2 would collapse 11 optimized titles into one.** v2 sets a single global title/description for the whole SPA. The migration map assigns per-page metadata explicitly so this cannot happen by default — treat any page whose title equals the home title as a build failure.
4. **HashRouter URLs** (`/#/weddings`) must never be deployed — they're invisible to crawlers. File routing eliminates this, but don't ship an interim SPA deploy.
5. **JSON-LD downgrades:** v2's `SchemaInjector` Florist block is thinner than live's (no `makesOffer`, no `@id`, wrong email potentially). Port from **live**, not from v2. Same for the FAQPage — live's 9 Q&As beat v2's 4.
6. **Don't lose:** `robots.txt` AI-crawler allows, `llms.txt`, canonical tags, security headers, `motif-divider.png` brand mark, 301s for `about.html`/`services.html` (now chained: `about.html → /story`).
7. **Renderability:** all indexable content SSG/SSR. Cart/account interactivity can hydrate client-side; product descriptions, prices, FAQs must be in the HTML payload.

### 5.3 How to rank #1 in Las Vegas (SEO + AI GEO)

Code-level (in scope for this migration):
- **27 product pages with `Product` schema + real photos + descriptive slugs** — competitors' florist sites rarely have per-arrangement pages with schema; this is the moat.
- **`Event` schema on dated workshops**, `Course` on classes, `FAQPage` everywhere relevant, `BreadcrumbList` sitewide, `LocalBusiness/Florist` with `geo` coordinates and real phone.
- **Location landing pages** (phase 2): `/flower-delivery-summerlin`, `/flower-delivery-henderson`, `/las-vegas-strip-wedding-florist` — thin-page risk if templated lazily; write real content per area (venues served, delivery windows).
- **Content hub** (phase 2): `/journal` with 6–10 intent pieces ("Las Vegas wedding florist cost guide", "best wedding venues in Las Vegas for florals", "what to expect at a floral-making class") — these are the queries AI engines answer with citations; llms.txt + FAQ + journal is the GEO trifecta.
- **Core Web Vitals:** SSG everything static, `next/image` with AVIF/WebP (the 26 PNGs are heavy — convert), font subsetting via `next/font`, zero layout shift on the hero.
- **Image SEO:** descriptive filenames + alt text (v2's alt text is already good — keep it).

Non-code (put on Brian/Ami's checklist — code can't do these and they matter more than any tag):
- **Google Business Profile** — claimed, categorized "Florist", real phone (the `(702) 000-0000` placeholder blocks this), photos, weekly posts. Local pack ranking is GBP-driven; the site's LocalBusiness schema must exactly match GBP NAP.
- **Reviews engine:** post-delivery email (automatable via Resend after `orders.status='delivered'`) asking for a Google review; mark up with `aggregateRating` once real ones exist. Replaces fabricated testimonials with the real thing.
- **Consistent NAP citations** (Yelp, The Knot, WeddingWire, Zola — the wedding directories double as high-authority backlinks).
- **Domain email** on Google Workspace (decided) with SPF/DKIM/DMARC — also fixes Resend deliverability.

---

## 6. Open Questions (resolve with Brian/Ami before the relevant task)

1. **Founder name spelling:** "Ami Nelson" (live story.html + JSON-LD) vs "AmiDayne Nelsen" (v2 FloristPage) vs "AmiDayne Nelson" (Drive about.html). Person schema, bylines, and GBP must match. → blocks A6.
2. **Contact email:** `hello@afuvai.com` (live, everywhere incl. functions) vs `admin@afuvai.com` (v2 + brief). Google Workspace decided — which address is canonical? → blocks A1 (footer), B4 (ops email).
3. **Catalog reconciliation:** ship v2's 27 products, live's 4×3 collection system, or both (27 signature + collections as "everyday line")? Bulk: keep live's ~20 per-stem SKUs (recommended — they exist and have recipes) alongside v2's 5 packages? Flower Purse price: $145 (live) vs $225/$285/$385 (v2). → blocks A2/B3.
4. **Subscription pricing lock** (brief flags this): confirm the v2 numbers above before creating Stripe Prices. Also: does Gold's "20% off all events & parties" perk ship v1 (needs a promo-code mechanism)? → blocks B5.
5. **Wedding minimum:** $3,500 (live, in FAQ + schema + llms.txt) vs $1,500 (v2 FAQ). Affects schema, FAQ, and lead qualification. → blocks A7.
6. **Typography:** live = Cormorant Garamond + Inter; v2 = Playfair Display + DM Sans. Palette is locked but fonts weren't addressed. Default if unanswered: v2 fonts (they're what the approved Figma design uses). → A1.
7. **Delivery promise:** "order by 1pm for next-day" (live shop) vs "order by 2pm for same-day" (v2) vs "same-day available" (live llms.txt + bulk hero). Pick one; it goes in schema, FAQ, checkout copy, and delivery-date validation logic. → A4/B3.
8. **Custom domain status:** did the GoDaddy DNS cutover (A `@` → `75.2.60.5`, CNAME `www`) complete and is `afuvai.com` serving the Netlify site with SSL? (Unverifiable from this sandbox.) Determines whether launch is a DNS no-op or includes the cutover. → C1.
9. **Venue name-drops:** v2 claims work at Bellagio/Wynn/Venetian/Caesars/Four Seasons ("Trusted at Las Vegas's finest venues") and portfolio venue labels. If not factual, this is a legal/brand risk — confirm or cut. Same for "1,200+ events / 6+ years / 4.9★". → A3/A6.
10. **Booking backend:** does `ConsultationBooking` need a real calendar (Cal.com embed or Google Calendar API against Ami's Workspace calendar) in v1, or is "persist request + Ami confirms by email" (B10) enough? Live site planned an Acuity/Calendly embed. Recommendation: B10 for launch, Cal.com in v2.1 — a fake availability checker must NOT ship either way.
11. **Real testimonials & remaining photos:** need ≥3 real client quotes (with permission) and photos for the 6 Unsplash-fallback products + section heroes (§8 shoot list). → C4.
12. **Repo placement** (see §7): approve creating `champagnebrian/afuvai` (recommended) or confirm staying in the `twenty` monorepo.

---

## 7. Recommended Execution Order

**Repo recommendation first:** move the Next.js app to a **fresh standalone repo (`champagnebrian/afuvai`)**. The static site already fought the twenty monorepo (Netlify base-dir hijacking, Yarn Berry workspace boundary, the empty-`yarn.lock` hack, `YARN_ENABLE_IMMUTABLE_INSTALLS=false`) — a Next build with its own lockfile inside an Nx/Yarn-4 workspace will hit all of that harder. A standalone repo makes Netlify config trivial and CI fast. If staying in-monorepo is preferred, use `afuvai-next/` with its own lockfile and expect one debugging session for CI. (Note: this Claude environment is currently scoped to `champagnebrian/twenty` only — creating/pushing a new repo needs Brian to adjust access or do the initial push.)

Phases sized to one Sonnet 5 session each unless marked:

| Phase | Sessions | Contents | Exit criteria |
|---|---:|---|---|
| **1. Scaffold + tokens** | 1 | A1 | Deployed preview on Netlify with nav/footer/palette, empty pages routed |
| **2. Content & data layer** | 1 | A2 | Typed content modules; photos renamed in `public/`; recipes merged |
| **3. Home + Shop** | 3 | A3, A4, A5 | Home, `/shop`, 27 product pages SSG with Product JSON-LD; cart persists; checkout button stubbed |
| **4. All static pages** | 4 | A6, A7 | Every §2 route live with per-page metadata; forms post to stub API |
| **5. SEO shell + parity audit** | 2 | A8, A9 | Redirects verified, robots/sitemap/llms.txt live, §5.1 table checked off page-by-page |
| **6. Supabase foundation** ⚑ Fable | 2–3 | B1, B2 | Migrations in repo; RLS tested; magic-link login → empty account shell |
| **7. Stripe checkout + webhooks** ⚑ Fable | 2 | B3, B4 | Test-mode purchase → order row + BOM ops email + receipt |
| **8. Subscriptions** ⚑ Fable | 1–2 | B5 | Subscribe/change/cancel via portal reflected in Supabase; dunning configured |
| **9. Account wiring** | 2 | B6 | All 6 tabs on real data; reminder emails scheduled |
| **10. Inquiries, newsletter, AI** | 2 | B7, B8, B9, B10 | Forms → Supabase + AI triage emails; Mailchimp double-opt-in working; suggest widget live |
| **11. Gift cards, classes, payments** | 2–3 | B11, B12, B13 | Gift card purchase→email→redeem loop; class seats decrement; deposit links live |
| **12. Launch** | 2–3 | C1, C2, C3 | Domain cutover, analytics + consent, full E2E incl. failed-payment path |
| **13. Content finalization** | 1 + human | C4 | Placeholders zero; real phone/bio/testimonials/photos |

Phases 1–5 have no backend dependency and can start immediately; §6 Q1/Q2/Q6 are the only blockers to start, Q3–Q5 needed by phase 2–3, and the photo/testimonial items only block phase 13.

---

## 8. Additional Recommendations (beyond the brief)

**Do in v1 (cheap, high leverage):**
1. **Post-delivery review-request email** (Resend, triggered when `orders.status` → `delivered`): builds the Google-review base that powers local ranking and replaces fabricated testimonials.
2. **Abandoned-checkout recovery:** Stripe Checkout `expires_at` + `checkout.session.expired` webhook → one tasteful recovery email. Florist AOV (~$150+) makes this pay for itself immediately.
3. **Delivery-date + zip validation done right:** validate zip against an actual LV-valley list (89002–89199 ranges), block past dates and same-day after cutoff in the date picker — v2 only checks "5 digits".
4. **`WhatsApp/SMS-able "our week" IG embed** → skip widgets; keep the static curated grid (fast, no third-party JS) but make it maintainable from Supabase or a JSON file.
5. **Convert the 26 product PNGs to AVIF/WebP via `next/image`** — they're phone-camera-size PNGs; this alone will decide mobile LCP.
6. **404 with product suggestions** (v2's copy "there are plenty of beautiful flowers waiting" + 3 bestsellers) — recovers misspelled/legacy URLs post-migration.

**v2.1 candidates (don't block launch):**
7. **Corporate/venue landing page + recurring-florals pitch** — live shop has a Corporate card; the recurring hotel/restaurant contract is the highest-LTV product AFUVAI sells and deserves its own funnel (`/corporate`).
8. **Journal/content hub + location pages** (§5.3) — the biggest organic-growth lever after product pages.
9. **Cal.com self-serve consultation booking** synced to Ami's Google Workspace calendar (replaces B10's request-only flow).
10. **Wishlist persistence** — v2's `wishlist` state is dead code today; with accounts it becomes "saved arrangements" + occasion-reminder cross-sell ("Mom's birthday in 2 weeks — you saved Blushing Garden").
11. **Occasion-reminder commerce loop** — reminders exist in schema (B6); v2.1 adds a one-click "send the same arrangement again" link in the reminder email. This is the retention engine for a florist.
12. **Referral/loyalty light:** Stripe promotion codes surfaced in account after Nth order.
13. **Per-product Subscribe & Save** (deferred from v1, §4.2).

**Ops list for Brian (non-code, start now — these gate ranking more than the code does):**
- Real phone number → GBP + site + schema (placeholder `(702) 000-0000` is live today).
- Google Business Profile claim + category + photos.
- Google Workspace domain email + SPF/DKIM/DMARC (fixes Resend/Mailchimp/magic-link deliverability in one move).
- Stripe team access for Brian on Ami's account; Mailchimp API key + audience ID.
- Rotate the Netlify token exposed in the Drive handoff doc.
- Photo shoot list: the 6 placeholder products (Summer Radiance, Heart of Remembrance, Blush Reverie, Festival Bloom, Pure Serenity, Golden Harvest), a studio/workshop scene (classes + parties heroes), a wide hero (or reuse `hero-arch`), add-on items (vase, chocolates, note card, preserved rose), and a founder portrait confirm (real `amiDayneImg` exists).
- Real testimonials (≥3, with names and permission) and confirmation/removal of venue claims (§6 Q9).
