import { errorResponse, handleOptions, jsonResponse } from '../_shared/cors.ts';
import { createServiceRoleClient, getUserIdFromRequest } from '../_shared/auth.ts';
import { checkRateLimit } from '../_shared/ratelimit.ts';
import {
  createAnthropicClient,
  DEMAND_LETTER_SYSTEM_PROMPT,
  LEASE_ANALYSIS_MODEL,
} from '../_shared/anthropic.ts';

const SUPPORTED_STATES = ['CA', 'NY', 'TX', 'FL', 'IL', 'NV'];
const LETTER_TYPES = [
  'deposit_return',
  'repair_request',
  'quiet_enjoyment',
  'lease_termination',
  'other',
];
const FREE_TIER_LETTERS_PER_MONTH = 3;
const RATE_LIMIT = 5;
const RATE_WINDOW_SECONDS = 3600;
const MAX_DETAILS_CHARS = 10_000;

type GenerateLetterRequest = {
  letter_type?: string;
  state_code?: string;
  document_id?: string | null;
  details?: string;
};

// Pro check is server-side against RevenueCat — a client-side flag is not
// trusted. The RevenueCat app user id is the Supabase uid (set at login).
const hasProEntitlement = async (userId: string): Promise<boolean> => {
  const secretKey = Deno.env.get('REVENUECAT_SECRET_KEY');
  if (secretKey === undefined) {
    console.error('generate-letter: REVENUECAT_SECRET_KEY missing — treating as free tier');
    return false;
  }
  try {
    const response = await fetch(
      `https://api.revenuecat.com/v1/subscribers/${encodeURIComponent(userId)}`,
      { headers: { Authorization: `Bearer ${secretKey}` } },
    );
    if (!response.ok) return false;
    const payload = (await response.json()) as {
      subscriber?: { entitlements?: Record<string, { expires_date: string | null }> };
    };
    const pro = payload.subscriber?.entitlements?.['pro'];
    if (pro === undefined) return false;
    return pro.expires_date === null || new Date(pro.expires_date) > new Date();
  } catch (error) {
    // Fail toward the free tier: an outage should never grant Pro.
    console.error('generate-letter: RevenueCat unreachable', error);
    return false;
  }
};

Deno.serve(async (req: Request): Promise<Response> => {
  const options = handleOptions(req);
  if (options !== null) return options;
  if (req.method !== 'POST') {
    return errorResponse(405, 'method_not_allowed', 'POST only');
  }

  const userId = await getUserIdFromRequest(req);
  if (userId === null) {
    return errorResponse(401, 'unauthorized', 'Missing or invalid access token');
  }

  const rate = await checkRateLimit('letter', userId, RATE_LIMIT, RATE_WINDOW_SECONDS);
  if (!rate.allowed) {
    return errorResponse(429, 'rate_limited', 'Too many letters — try again later', {
      retry_after_seconds: rate.retryAfterSeconds,
    });
  }

  let body: GenerateLetterRequest;
  try {
    body = await req.json();
  } catch {
    return errorResponse(400, 'invalid_json', 'Body must be JSON');
  }

  const { letter_type: letterType, state_code: stateCode, details } = body;
  const documentId = body.document_id ?? null;

  if (typeof letterType !== 'string' || !LETTER_TYPES.includes(letterType)) {
    return errorResponse(422, 'invalid_letter_type', `letter_type must be one of ${LETTER_TYPES.join(', ')}`);
  }
  if (typeof stateCode !== 'string' || !SUPPORTED_STATES.includes(stateCode)) {
    return errorResponse(422, 'unsupported_state', `state_code must be one of ${SUPPORTED_STATES.join(', ')}`);
  }
  if (typeof details !== 'string' || details.trim().length === 0) {
    return errorResponse(422, 'invalid_request', 'details is required');
  }
  if (details.length > MAX_DETAILS_CHARS) {
    return errorResponse(413, 'details_too_long', 'details exceeds the size limit');
  }

  const supabase = createServiceRoleClient();

  // Free-tier cap, enforced server-side per UTC calendar month.
  const isPro = await hasProEntitlement(userId);
  if (!isPro) {
    const now = new Date();
    const monthStart = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)).toISOString();
    const { count, error: countError } = await supabase
      .from('letters')
      .select('id', { count: 'exact', head: true })
      .eq('user_id', userId)
      .gte('created_at', monthStart);
    if (countError !== null) {
      return errorResponse(500, 'db_error', 'Could not check letter usage');
    }
    if ((count ?? 0) >= FREE_TIER_LETTERS_PER_MONTH) {
      return errorResponse(402, 'letter_cap_reached', 'Free tier includes 3 letters per month — upgrade to Pro for unlimited letters');
    }
  }

  if (documentId !== null) {
    const { data: document } = await supabase
      .from('documents')
      .select('id')
      .eq('id', documentId)
      .eq('user_id', userId)
      .maybeSingle();
    if (document === null) {
      return errorResponse(404, 'document_not_found', 'No such document for this user');
    }
  }

  let letterBody: string;
  try {
    const anthropic = createAnthropicClient();
    const response = await anthropic.messages.create({
      model: LEASE_ANALYSIS_MODEL,
      max_tokens: 16000,
      system: DEMAND_LETTER_SYSTEM_PROMPT,
      messages: [
        {
          role: 'user',
          content: `Letter type: ${letterType}\nTenant's state: ${stateCode}\n\nSituation (privacy-tokenized):\n\n${details}`,
        },
      ],
    });

    if (response.stop_reason === 'refusal') {
      throw new Error('model_refusal');
    }

    const textBlock = response.content.find((block) => block.type === 'text');
    if (textBlock === undefined || textBlock.type !== 'text') {
      throw new Error('no_text_block');
    }
    letterBody = textBlock.text;
  } catch (error) {
    console.error('generate-letter: model call failed', error instanceof Error ? error.message : 'unknown');
    return errorResponse(502, 'generation_failed', 'Letter generation failed — please try again');
  }

  const { data: letter, error: insertError } = await supabase
    .from('letters')
    .insert({
      user_id: userId,
      document_id: documentId,
      letter_type: letterType,
      body_tokenized: letterBody,
    })
    .select()
    .single();
  if (insertError !== null) {
    return errorResponse(500, 'db_error', 'Could not save the letter');
  }

  return jsonResponse({ letter });
});
