import { errorResponse, handleOptions, jsonResponse } from '../_shared/cors.ts';
import { createServiceRoleClient, getUserIdFromRequest } from '../_shared/auth.ts';
import { checkRateLimit } from '../_shared/ratelimit.ts';
import {
  createAnthropicClient,
  FLAGS_OUTPUT_SCHEMA,
  LEASE_ANALYSIS_MODEL,
  LEASE_ANALYSIS_SYSTEM_PROMPT,
} from '../_shared/anthropic.ts';

const SUPPORTED_STATES = ['CA', 'NY', 'TX', 'FL', 'IL', 'NV'];
const MAX_LEASE_CHARS = 150_000;
const MIN_LEASE_CHARS = 200;
const RATE_LIMIT = 5;
const RATE_WINDOW_SECONDS = 3600;

type AnalyzeRequest = {
  document_id?: string;
  state_code?: string;
  lease_text?: string;
};

type Flag = {
  severity: 'high' | 'medium' | 'low';
  clause_quote: string;
  explanation: string;
  suggested_action: string;
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

  const rate = await checkRateLimit('analyze', userId, RATE_LIMIT, RATE_WINDOW_SECONDS);
  if (!rate.allowed) {
    return errorResponse(429, 'rate_limited', 'Too many analyses — try again later', {
      retry_after_seconds: rate.retryAfterSeconds,
    });
  }

  let body: AnalyzeRequest;
  try {
    body = await req.json();
  } catch {
    return errorResponse(400, 'invalid_json', 'Body must be JSON');
  }

  const { document_id: documentId, state_code: stateCode, lease_text: leaseText } = body;
  if (typeof documentId !== 'string' || typeof leaseText !== 'string') {
    return errorResponse(422, 'invalid_request', 'document_id and lease_text are required');
  }
  if (typeof stateCode !== 'string' || !SUPPORTED_STATES.includes(stateCode)) {
    return errorResponse(422, 'unsupported_state', `state_code must be one of ${SUPPORTED_STATES.join(', ')}`);
  }
  if (leaseText.length > MAX_LEASE_CHARS) {
    return errorResponse(413, 'lease_too_long', 'Lease text exceeds the size limit');
  }
  if (leaseText.trim().length < MIN_LEASE_CHARS) {
    return errorResponse(422, 'lease_too_short', 'Not enough text to analyze — try the OCR or paste option');
  }

  const supabase = createServiceRoleClient();

  // Ownership check is against the JWT-derived user id, never the body.
  const { data: document, error: documentError } = await supabase
    .from('documents')
    .select('id')
    .eq('id', documentId)
    .eq('user_id', userId)
    .maybeSingle();
  if (documentError !== null) {
    return errorResponse(500, 'db_error', 'Could not load document');
  }
  if (document === null) {
    return errorResponse(404, 'document_not_found', 'No such document for this user');
  }

  await supabase.from('documents').update({ status: 'analyzing' }).eq('id', documentId);

  let flags: Flag[];
  try {
    const anthropic = createAnthropicClient();
    const response = await anthropic.messages.create({
      model: LEASE_ANALYSIS_MODEL,
      max_tokens: 16000,
      system: LEASE_ANALYSIS_SYSTEM_PROMPT,
      output_config: {
        format: {
          type: 'json_schema',
          schema: FLAGS_OUTPUT_SCHEMA,
        },
      },
      messages: [
        {
          role: 'user',
          content: `Tenant's state: ${stateCode}\n\nLease text (privacy-tokenized):\n\n${leaseText}`,
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
    flags = (JSON.parse(textBlock.text) as { flags: Flag[] }).flags;
  } catch (error) {
    // Never echo provider errors — they can contain prompt content.
    console.error('analyze-lease: model call failed', error instanceof Error ? error.message : 'unknown');
    await supabase.from('documents').update({ status: 'failed' }).eq('id', documentId);
    return errorResponse(502, 'analysis_failed', 'Analysis failed — please try again');
  }

  const rows = flags.map((flag) => ({
    user_id: userId,
    document_id: documentId,
    severity: flag.severity,
    clause_quote: flag.clause_quote,
    explanation: flag.explanation,
    suggested_action: flag.suggested_action,
  }));

  if (rows.length > 0) {
    const { error: insertError } = await supabase.from('flags').insert(rows);
    if (insertError !== null) {
      await supabase.from('documents').update({ status: 'failed' }).eq('id', documentId);
      return errorResponse(500, 'db_error', 'Could not save analysis results');
    }
  }

  await supabase.from('documents').update({ status: 'analyzed' }).eq('id', documentId);

  return jsonResponse({ flags: rows });
});
