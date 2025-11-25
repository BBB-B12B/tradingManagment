import type { D1Database } from '@cloudflare/workers-types';

/**
 * CDC Zone Bot - Cloudflare Worker API
 *
 * This worker provides D1 database access for:
 * - Position states (FLAT/LONG tracking)
 * - Order history (trade records)
 * - Trading sessions (completed trades)
 * - Circuit breaker state
 */

export interface Env {
  CDC_DB: D1Database;
  ENV: string;
  API_TOKEN?: string;
}

/**
 * Main request handler
 */
export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // CORS headers
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    try {
      const authError = authorizeRequest(request, env, corsHeaders);
      if (authError) {
        return authError;
      }

      // Health check
      if (path === '/' || path === '/health') {
        return jsonResponse({ status: 'ok', service: 'cdc-zone-worker' }, corsHeaders);
      }

      // Route to handlers
      if (path.startsWith('/positions')) {
        return handlePositions(request, env, url, corsHeaders);
      }

      if (path.startsWith('/orders')) {
        return handleOrders(request, env, path, corsHeaders);
      }

      if (path.startsWith('/sessions')) {
        return handleSessions(request, env, path, corsHeaders);
      }

      if (path.startsWith('/circuit-breaker')) {
        return handleCircuitBreaker(request, env, path, corsHeaders);
      }

      return jsonResponse({ error: 'Not Found' }, corsHeaders, 404);
    } catch (error) {
      console.error('Error:', error);
      return jsonResponse(
        { error: 'Internal Server Error', message: (error as Error).message },
        corsHeaders,
        500
      );
    }
  },
};

/**
 * Position state handlers
 */
async function handlePositions(
  request: Request,
  env: Env,
  url: URL,
  corsHeaders: Record<string, string>
): Promise<Response> {
  const method = request.method;
  const path = url.pathname;
  const statusFilter = url.searchParams.get('status');

  // GET /positions - List all positions
  if (path === '/positions' && method === 'GET') {
    let query = 'SELECT * FROM position_states';
    const bindings: string[] = [];

    if (statusFilter) {
      query += ' WHERE status = ?';
      bindings.push(statusFilter.toUpperCase());
    }

    query += ' ORDER BY pair';
    let statement = env.CDC_DB.prepare(query);
    if (bindings.length) {
      statement = statement.bind(...bindings);
    }
    const result = await statement.all();

    return jsonResponse({ positions: result.results }, corsHeaders);
  }

  // GET /positions/:pair - Get specific position
  if (path.startsWith('/positions/') && method === 'GET') {
    const pair = decodeURIComponent(path.split('/positions/')[1]);

    const result = await env.CDC_DB.prepare(
      'SELECT * FROM position_states WHERE pair = ?'
    ).bind(pair.toUpperCase()).first();

    if (!result) {
      // Auto-create FLAT position if not exists
      const now = new Date().toISOString();
      await env.CDC_DB.prepare(
        `INSERT INTO position_states (pair, status, last_update_time, created_at, updated_at)
         VALUES (?, 'FLAT', ?, ?, ?)`
      ).bind(pair.toUpperCase(), now, now, now).run();

      const newPosition = await env.CDC_DB.prepare(
        'SELECT * FROM position_states WHERE pair = ?'
      ).bind(pair.toUpperCase()).first();

      return jsonResponse({ position: newPosition }, corsHeaders);
    }

    return jsonResponse({ position: result }, corsHeaders);
  }

  // POST /positions - Update position state
  if (path === '/positions' && method === 'POST') {
    const body = await request.json() as any;
    const { pair, status, entry_price, entry_time, entry_bar_index, w_low, sl_price, qty } = body;

    const now = new Date().toISOString();

    // Check if position exists
    const existing = await env.CDC_DB.prepare(
      'SELECT * FROM position_states WHERE pair = ?'
    ).bind(pair.toUpperCase()).first();

    if (existing) {
      // Update existing position
      await env.CDC_DB.prepare(
        `UPDATE position_states
         SET status = ?, entry_price = ?, entry_time = ?, entry_bar_index = ?,
             w_low = ?, sl_price = ?, qty = ?, last_update_time = ?, updated_at = ?
         WHERE pair = ?`
      ).bind(
        status || 'FLAT',
        entry_price || null,
        entry_time || null,
        entry_bar_index || null,
        w_low || null,
        sl_price || null,
        qty || null,
        now,
        now,
        pair.toUpperCase()
      ).run();
    } else {
      // Insert new position
      await env.CDC_DB.prepare(
        `INSERT INTO position_states
         (pair, status, entry_price, entry_time, entry_bar_index, w_low, sl_price, qty, last_update_time, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
      ).bind(
        pair.toUpperCase(),
        status || 'FLAT',
        entry_price || null,
        entry_time || null,
        entry_bar_index || null,
        w_low || null,
        sl_price || null,
        qty || null,
        now,
        now,
        now
      ).run();
    }

    // Fetch and return updated position
    const updated = await env.CDC_DB.prepare(
      'SELECT * FROM position_states WHERE pair = ?'
    ).bind(pair.toUpperCase()).first();

    return jsonResponse({ position: updated }, corsHeaders);
  }

  // DELETE /positions/:pair - Delete existing position
  if (path.startsWith('/positions/') && method === 'DELETE') {
    const pair = decodeURIComponent(path.split('/positions/')[1]);

    const result = await env.CDC_DB.prepare(
      'DELETE FROM position_states WHERE pair = ?'
    ).bind(pair.toUpperCase()).run();

    if ((result.meta.changes || 0) === 0) {
      return jsonResponse({ error: 'Position not found' }, corsHeaders, 404);
    }

    return jsonResponse({ status: 'deleted', pair: pair.toUpperCase() }, corsHeaders);
  }

  return jsonResponse({ error: 'Method not allowed' }, corsHeaders, 405);
}

/**
 * Order history handlers
 */
async function handleOrders(
  request: Request,
  env: Env,
  path: string,
  corsHeaders: Record<string, string>
): Promise<Response> {
  const method = request.method;

  // GET /orders - List orders with optional filters
  if (path === '/orders' && method === 'GET') {
    const url = new URL(request.url);
    const pair = url.searchParams.get('pair');
    const limit = parseInt(url.searchParams.get('limit') || '100');

    let query = 'SELECT * FROM order_history';
    const bindings: any[] = [];

    if (pair) {
      query += ' WHERE pair = ?';
      bindings.push(pair.toUpperCase());
    }

    query += ' ORDER BY created_at DESC LIMIT ?';
    bindings.push(limit);

    const result = await env.CDC_DB.prepare(query).bind(...bindings).all();

    return jsonResponse({ orders: result.results }, corsHeaders);
  }

  // POST /orders - Record new order
  if (path === '/orders' && method === 'POST') {
    const body = await request.json() as any;
    const {
      pair, order_type, side, requested_qty, filled_qty, avg_price,
      order_id, status, entry_reason, exit_reason,
      rule_1_cdc_green, rule_2_leading_red, rule_3_leading_signal, rule_4_pattern,
      entry_price, exit_price, pnl, pnl_pct,
      w_low, sl_price, requested_at, filled_at
    } = body;

    const now = new Date().toISOString();

    const result = await env.CDC_DB.prepare(
      `INSERT INTO order_history (
        pair, order_type, side, requested_qty, filled_qty, avg_price,
        order_id, status, entry_reason, exit_reason,
        rule_1_cdc_green, rule_2_leading_red, rule_3_leading_signal, rule_4_pattern,
        entry_price, exit_price, pnl, pnl_pct,
        w_low, sl_price, requested_at, filled_at, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).bind(
      pair.toUpperCase(), order_type, side, requested_qty, filled_qty, avg_price,
      order_id, status, entry_reason, exit_reason,
      rule_1_cdc_green ? 1 : 0,
      rule_2_leading_red ? 1 : 0,
      rule_3_leading_signal ? 1 : 0,
      rule_4_pattern ? 1 : 0,
      entry_price, exit_price, pnl, pnl_pct,
      w_low, sl_price, requested_at, filled_at, now
    ).run();

    return jsonResponse({
      success: true,
      order_id: result.meta.last_row_id
    }, corsHeaders);
  }

  return jsonResponse({ error: 'Method not allowed' }, corsHeaders, 405);
}

/**
 * Trading sessions handlers
 */
async function handleSessions(
  request: Request,
  env: Env,
  path: string,
  corsHeaders: Record<string, string>
): Promise<Response> {
  const method = request.method;

  // GET /sessions - List trading sessions
  if (path === '/sessions' && method === 'GET') {
    const url = new URL(request.url);
    const pair = url.searchParams.get('pair');
    const limit = parseInt(url.searchParams.get('limit') || '50');

    let query = 'SELECT * FROM trading_sessions';
    const bindings: any[] = [];

    if (pair) {
      query += ' WHERE pair = ?';
      bindings.push(pair.toUpperCase());
    }

    query += ' ORDER BY created_at DESC LIMIT ?';
    bindings.push(limit);

    const result = await env.CDC_DB.prepare(query).bind(...bindings).all();

    return jsonResponse({ sessions: result.results }, corsHeaders);
  }

  // POST /sessions - Create trading session
  if (path === '/sessions' && method === 'POST') {
    const body = await request.json() as any;
    const {
      pair, entry_order_id, entry_time, entry_price, entry_qty,
      exit_order_id, exit_time, exit_price, exit_qty, exit_reason,
      pnl, pnl_pct, entry_rules_passed
    } = body;

    const now = new Date().toISOString();

    const result = await env.CDC_DB.prepare(
      `INSERT INTO trading_sessions (
        pair, entry_order_id, entry_time, entry_price, entry_qty,
        exit_order_id, exit_time, exit_price, exit_qty, exit_reason,
        pnl, pnl_pct, entry_rules_passed, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).bind(
      pair.toUpperCase(), entry_order_id, entry_time, entry_price, entry_qty,
      exit_order_id, exit_time, exit_price, exit_qty, exit_reason,
      pnl, pnl_pct, entry_rules_passed, now
    ).run();

    return jsonResponse({
      success: true,
      session_id: result.meta.last_row_id
    }, corsHeaders);
  }

  return jsonResponse({ error: 'Method not allowed' }, corsHeaders, 405);
}

/**
 * Circuit breaker handlers
 */
async function handleCircuitBreaker(
  request: Request,
  env: Env,
  path: string,
  corsHeaders: Record<string, string>
): Promise<Response> {
  const method = request.method;

  // GET /circuit-breaker - Get circuit breaker state
  if (path === '/circuit-breaker' && method === 'GET') {
    const result = await env.CDC_DB.prepare(
      'SELECT * FROM circuit_breaker_state WHERE id = 1'
    ).first();

    return jsonResponse({ circuit_breaker: result }, corsHeaders);
  }

  // POST /circuit-breaker - Update circuit breaker state
  if (path === '/circuit-breaker' && method === 'POST') {
    const body = await request.json() as any;
    const { is_active, reason, daily_loss, daily_loss_pct, total_drawdown_pct, activated_at } = body;

    const now = new Date().toISOString();

    await env.CDC_DB.prepare(
      `UPDATE circuit_breaker_state
       SET is_active = ?, reason = ?, daily_loss = ?, daily_loss_pct = ?,
           total_drawdown_pct = ?, activated_at = ?, updated_at = ?
       WHERE id = 1`
    ).bind(
      is_active ? 1 : 0,
      reason || null,
      daily_loss || 0,
      daily_loss_pct || 0,
      total_drawdown_pct || 0,
      activated_at || null,
      now
    ).run();

    const updated = await env.CDC_DB.prepare(
      'SELECT * FROM circuit_breaker_state WHERE id = 1'
    ).first();

    return jsonResponse({ circuit_breaker: updated }, corsHeaders);
  }

  return jsonResponse({ error: 'Method not allowed' }, corsHeaders, 405);
}

/**
 * Helper function to create JSON responses
 */
function jsonResponse(
  data: any,
  headers: Record<string, string> = {},
  status: number = 200
): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
  });
}

function authorizeRequest(
  request: Request,
  env: Env,
  corsHeaders: Record<string, string>
): Response | null {
  if (!env.API_TOKEN) {
    return null;
  }

  const header = request.headers.get('Authorization') || '';
  const [scheme, token] = header.split(' ');

  if (scheme?.toLowerCase() !== 'bearer' || token !== env.API_TOKEN) {
    return jsonResponse(
      { error: 'Unauthorized' },
      corsHeaders,
      401,
    );
  }

  return null;
}
