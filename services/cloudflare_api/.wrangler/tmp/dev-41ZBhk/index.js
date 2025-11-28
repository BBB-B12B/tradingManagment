var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });

// src/index.ts
var src_default = {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type"
    };
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }
    try {
      const authError = authorizeRequest(request, env, corsHeaders);
      if (authError) {
        return authError;
      }
      if (path === "/" || path === "/health") {
        return jsonResponse({ status: "ok", service: "cdc-zone-worker" }, corsHeaders);
      }
      if (path.startsWith("/positions")) {
        return handlePositions(request, env, url, corsHeaders);
      }
      if (path.startsWith("/orders")) {
        return handleOrders(request, env, path, corsHeaders);
      }
      if (path.startsWith("/sessions")) {
        return handleSessions(request, env, path, corsHeaders);
      }
      if (path.startsWith("/circuit-breaker")) {
        return handleCircuitBreaker(request, env, path, corsHeaders);
      }
      if (path.startsWith("/config")) {
        return handleConfigs(request, env, url, corsHeaders);
      }
      return jsonResponse({ error: "Not Found" }, corsHeaders, 404);
    } catch (error) {
      console.error("Error:", error);
      return jsonResponse(
        { error: "Internal Server Error", message: error.message },
        corsHeaders,
        500
      );
    }
  }
};
async function handlePositions(request, env, url, corsHeaders) {
  const method = request.method;
  const path = url.pathname;
  const statusFilter = url.searchParams.get("status");
  if (path === "/positions" && method === "GET") {
    let query = "SELECT * FROM position_states";
    const bindings = [];
    if (statusFilter) {
      query += " WHERE status = ?";
      bindings.push(statusFilter.toUpperCase());
    }
    query += " ORDER BY pair";
    let statement = env.CDC_DB.prepare(query);
    if (bindings.length) {
      statement = statement.bind(...bindings);
    }
    const result = await statement.all();
    return jsonResponse({ positions: result.results }, corsHeaders);
  }
  if (path.startsWith("/positions/") && method === "GET") {
    const pair = decodeURIComponent(path.split("/positions/")[1]);
    const result = await env.CDC_DB.prepare(
      "SELECT * FROM position_states WHERE pair = ?"
    ).bind(pair.toUpperCase()).first();
    if (!result) {
      const now = (/* @__PURE__ */ new Date()).toISOString();
      await env.CDC_DB.prepare(
        `INSERT INTO position_states (pair, status, last_update_time, created_at, updated_at)
         VALUES (?, 'FLAT', ?, ?, ?)`
      ).bind(pair.toUpperCase(), now, now, now).run();
      const newPosition = await env.CDC_DB.prepare(
        "SELECT * FROM position_states WHERE pair = ?"
      ).bind(pair.toUpperCase()).first();
      return jsonResponse({ position: newPosition }, corsHeaders);
    }
    return jsonResponse({ position: result }, corsHeaders);
  }
  if (path === "/positions" && method === "POST") {
    const body = await request.json();
    const { pair, status, entry_price, entry_time, entry_bar_index, w_low, sl_price, qty } = body;
    const now = (/* @__PURE__ */ new Date()).toISOString();
    const existing = await env.CDC_DB.prepare(
      "SELECT * FROM position_states WHERE pair = ?"
    ).bind(pair.toUpperCase()).first();
    if (existing) {
      await env.CDC_DB.prepare(
        `UPDATE position_states
         SET status = ?, entry_price = ?, entry_time = ?, entry_bar_index = ?,
             w_low = ?, sl_price = ?, qty = ?, last_update_time = ?, updated_at = ?
         WHERE pair = ?`
      ).bind(
        status || "FLAT",
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
      await env.CDC_DB.prepare(
        `INSERT INTO position_states
         (pair, status, entry_price, entry_time, entry_bar_index, w_low, sl_price, qty, last_update_time, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
      ).bind(
        pair.toUpperCase(),
        status || "FLAT",
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
    const updated = await env.CDC_DB.prepare(
      "SELECT * FROM position_states WHERE pair = ?"
    ).bind(pair.toUpperCase()).first();
    return jsonResponse({ position: updated }, corsHeaders);
  }
  if (path.startsWith("/positions/") && method === "DELETE") {
    const pair = decodeURIComponent(path.split("/positions/")[1]);
    const result = await env.CDC_DB.prepare(
      "DELETE FROM position_states WHERE pair = ?"
    ).bind(pair.toUpperCase()).run();
    if ((result.meta.changes || 0) === 0) {
      return jsonResponse({ error: "Position not found" }, corsHeaders, 404);
    }
    return jsonResponse({ status: "deleted", pair: pair.toUpperCase() }, corsHeaders);
  }
  return jsonResponse({ error: "Method not allowed" }, corsHeaders, 405);
}
__name(handlePositions, "handlePositions");
async function handleOrders(request, env, path, corsHeaders) {
  const method = request.method;
  if (path === "/orders" && method === "GET") {
    const url = new URL(request.url);
    const pair = url.searchParams.get("pair");
    const limit = parseInt(url.searchParams.get("limit") || "100");
    let query = "SELECT * FROM order_history";
    const bindings = [];
    if (pair) {
      query += " WHERE pair = ?";
      bindings.push(pair.toUpperCase());
    }
    query += " ORDER BY created_at DESC LIMIT ?";
    bindings.push(limit);
    const result = await env.CDC_DB.prepare(query).bind(...bindings).all();
    return jsonResponse({ orders: result.results }, corsHeaders);
  }
  if (path === "/orders" && method === "POST") {
    const body = await request.json();
    const {
      pair,
      order_type,
      side,
      requested_qty,
      filled_qty,
      avg_price,
      order_id,
      status,
      entry_reason,
      exit_reason,
      rule_1_cdc_green,
      rule_2_leading_red,
      rule_3_leading_signal,
      rule_4_pattern,
      entry_price,
      exit_price,
      pnl,
      pnl_pct,
      w_low,
      sl_price,
      requested_at,
      filled_at
    } = body;
    const now = (/* @__PURE__ */ new Date()).toISOString();
    const result = await env.CDC_DB.prepare(
      `INSERT INTO order_history (
        pair, order_type, side, requested_qty, filled_qty, avg_price,
        order_id, status, entry_reason, exit_reason,
        rule_1_cdc_green, rule_2_leading_red, rule_3_leading_signal, rule_4_pattern,
        entry_price, exit_price, pnl, pnl_pct,
        w_low, sl_price, requested_at, filled_at, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).bind(
      pair.toUpperCase(),
      order_type,
      side,
      requested_qty,
      filled_qty,
      avg_price,
      order_id,
      status,
      entry_reason,
      exit_reason,
      rule_1_cdc_green ? 1 : 0,
      rule_2_leading_red ? 1 : 0,
      rule_3_leading_signal ? 1 : 0,
      rule_4_pattern ? 1 : 0,
      entry_price,
      exit_price,
      pnl,
      pnl_pct,
      w_low,
      sl_price,
      requested_at,
      filled_at,
      now
    ).run();
    return jsonResponse({
      success: true,
      order_id: result.meta.last_row_id
    }, corsHeaders);
  }
  return jsonResponse({ error: "Method not allowed" }, corsHeaders, 405);
}
__name(handleOrders, "handleOrders");
async function handleSessions(request, env, path, corsHeaders) {
  const method = request.method;
  if (path === "/sessions" && method === "GET") {
    const url = new URL(request.url);
    const pair = url.searchParams.get("pair");
    const limit = parseInt(url.searchParams.get("limit") || "50");
    let query = "SELECT * FROM trading_sessions";
    const bindings = [];
    if (pair) {
      query += " WHERE pair = ?";
      bindings.push(pair.toUpperCase());
    }
    query += " ORDER BY created_at DESC LIMIT ?";
    bindings.push(limit);
    const result = await env.CDC_DB.prepare(query).bind(...bindings).all();
    return jsonResponse({ sessions: result.results }, corsHeaders);
  }
  if (path === "/sessions" && method === "POST") {
    const body = await request.json();
    const {
      pair,
      entry_order_id,
      entry_time,
      entry_price,
      entry_qty,
      exit_order_id,
      exit_time,
      exit_price,
      exit_qty,
      exit_reason,
      pnl,
      pnl_pct,
      entry_rules_passed
    } = body;
    const now = (/* @__PURE__ */ new Date()).toISOString();
    const result = await env.CDC_DB.prepare(
      `INSERT INTO trading_sessions (
        pair, entry_order_id, entry_time, entry_price, entry_qty,
        exit_order_id, exit_time, exit_price, exit_qty, exit_reason,
        pnl, pnl_pct, entry_rules_passed, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).bind(
      pair.toUpperCase(),
      entry_order_id,
      entry_time,
      entry_price,
      entry_qty,
      exit_order_id,
      exit_time,
      exit_price,
      exit_qty,
      exit_reason,
      pnl,
      pnl_pct,
      entry_rules_passed,
      now
    ).run();
    return jsonResponse({
      success: true,
      session_id: result.meta.last_row_id
    }, corsHeaders);
  }
  return jsonResponse({ error: "Method not allowed" }, corsHeaders, 405);
}
__name(handleSessions, "handleSessions");
async function handleConfigs(request, env, url, corsHeaders) {
  const method = request.method;
  const path = url.pathname;
  if (path === "/config/list" && method === "GET") {
    const result = await env.CDC_DB.prepare(
      "SELECT pair FROM trading_configurations ORDER BY pair"
    ).all();
    const pairs = result.results.map((row) => row.pair);
    return jsonResponse({ pairs, count: pairs.length }, corsHeaders);
  }
  if (path === "/config" && method === "GET") {
    const pair = url.searchParams.get("pair");
    if (!pair) {
      return jsonResponse({ error: "pair parameter required" }, corsHeaders, 400);
    }
    const result = await env.CDC_DB.prepare(
      "SELECT * FROM trading_configurations WHERE pair = ?"
    ).bind(pair.toUpperCase()).first();
    if (!result) {
      return jsonResponse({ error: "config not found" }, corsHeaders, 404);
    }
    const config = {
      pair: result.pair,
      timeframe: result.timeframe,
      enable_w_shape_filter: Boolean(result.enable_w_shape),
      enable_leading_signal: Boolean(result.enable_leading_signal),
      risk: JSON.parse(result.risk_json),
      rule_params: JSON.parse(result.rule_params_json)
    };
    return jsonResponse(config, corsHeaders);
  }
  if (path === "/config" && method === "POST") {
    const body = await request.json();
    const { config } = body;
    if (!config || !config.pair) {
      return jsonResponse({ error: "config.pair is required" }, corsHeaders, 400);
    }
    const pair = config.pair.toUpperCase();
    const countResult = await env.CDC_DB.prepare(
      "SELECT COUNT(*) as count FROM trading_configurations WHERE pair != ?"
    ).bind(pair).first();
    if (countResult.count >= 5) {
      const existing2 = await env.CDC_DB.prepare(
        "SELECT * FROM trading_configurations WHERE pair = ?"
      ).bind(pair).first();
      if (!existing2) {
        return jsonResponse({
          error: "Maximum of 5 active configs reached. Please remove an existing pair before adding a new one."
        }, corsHeaders, 400);
      }
    }
    const riskJson = JSON.stringify(config.risk || {
      per_trade_cap_pct: 0.1,
      max_drawdown_pct: 20,
      daily_loss_limit_pct: 5
    });
    const ruleParamsJson = JSON.stringify(config.rule_params || {
      cdc_threshold: 0,
      leading_signal_threshold: 0
    });
    const existing = await env.CDC_DB.prepare(
      "SELECT * FROM trading_configurations WHERE pair = ?"
    ).bind(pair).first();
    if (existing) {
      await env.CDC_DB.prepare(
        `UPDATE trading_configurations
         SET timeframe = ?, enable_w_shape = ?, enable_leading_signal = ?,
             risk_json = ?, rule_params_json = ?
         WHERE pair = ?`
      ).bind(
        config.timeframe || "1d",
        config.enable_w_shape_filter ? 1 : 0,
        config.enable_leading_signal ? 1 : 0,
        riskJson,
        ruleParamsJson,
        pair
      ).run();
    } else {
      const budgetPct = config.risk?.per_trade_cap_pct || 0.1;
      await env.CDC_DB.prepare(
        `INSERT INTO trading_configurations
         (pair, timeframe, budget_pct, enable_w_shape, enable_leading_signal, risk_json, rule_params_json, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
      ).bind(
        pair,
        config.timeframe || "1d",
        budgetPct,
        config.enable_w_shape_filter ? 1 : 0,
        config.enable_leading_signal ? 1 : 0,
        riskJson,
        ruleParamsJson,
        (/* @__PURE__ */ new Date()).toISOString()
      ).run();
    }
    return jsonResponse({ status: "ok", pair }, corsHeaders);
  }
  if (path === "/config" && method === "DELETE") {
    const pair = url.searchParams.get("pair");
    if (!pair) {
      return jsonResponse({ error: "pair parameter required" }, corsHeaders, 400);
    }
    const result = await env.CDC_DB.prepare(
      "DELETE FROM trading_configurations WHERE pair = ?"
    ).bind(pair.toUpperCase()).run();
    if ((result.meta.changes || 0) === 0) {
      return jsonResponse({ error: "config not found" }, corsHeaders, 404);
    }
    return jsonResponse({ status: "deleted", pair: pair.toUpperCase() }, corsHeaders);
  }
  return jsonResponse({ error: "Method not allowed" }, corsHeaders, 405);
}
__name(handleConfigs, "handleConfigs");
async function handleCircuitBreaker(request, env, path, corsHeaders) {
  const method = request.method;
  if (path === "/circuit-breaker" && method === "GET") {
    const result = await env.CDC_DB.prepare(
      "SELECT * FROM circuit_breaker_state WHERE id = 1"
    ).first();
    return jsonResponse({ circuit_breaker: result }, corsHeaders);
  }
  if (path === "/circuit-breaker" && method === "POST") {
    const body = await request.json();
    const { is_active, reason, daily_loss, daily_loss_pct, total_drawdown_pct, activated_at } = body;
    const now = (/* @__PURE__ */ new Date()).toISOString();
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
      "SELECT * FROM circuit_breaker_state WHERE id = 1"
    ).first();
    return jsonResponse({ circuit_breaker: updated }, corsHeaders);
  }
  return jsonResponse({ error: "Method not allowed" }, corsHeaders, 405);
}
__name(handleCircuitBreaker, "handleCircuitBreaker");
function jsonResponse(data, headers = {}, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...headers
    }
  });
}
__name(jsonResponse, "jsonResponse");
function authorizeRequest(request, env, corsHeaders) {
  if (!env.API_TOKEN) {
    return null;
  }
  const header = request.headers.get("Authorization") || "";
  const [scheme, token] = header.split(" ");
  if (scheme?.toLowerCase() !== "bearer" || token !== env.API_TOKEN) {
    return jsonResponse(
      { error: "Unauthorized" },
      corsHeaders,
      401
    );
  }
  return null;
}
__name(authorizeRequest, "authorizeRequest");

// ../../../../../IDE/nvm/versions/node/v20.19.5/lib/node_modules/wrangler/templates/middleware/middleware-ensure-req-body-drained.ts
var drainBody = /* @__PURE__ */ __name(async (request, env, _ctx, middlewareCtx) => {
  try {
    return await middlewareCtx.next(request, env);
  } finally {
    try {
      if (request.body !== null && !request.bodyUsed) {
        const reader = request.body.getReader();
        while (!(await reader.read()).done) {
        }
      }
    } catch (e) {
      console.error("Failed to drain the unused request body.", e);
    }
  }
}, "drainBody");
var middleware_ensure_req_body_drained_default = drainBody;

// ../../../../../IDE/nvm/versions/node/v20.19.5/lib/node_modules/wrangler/templates/middleware/middleware-miniflare3-json-error.ts
function reduceError(e) {
  return {
    name: e?.name,
    message: e?.message ?? String(e),
    stack: e?.stack,
    cause: e?.cause === void 0 ? void 0 : reduceError(e.cause)
  };
}
__name(reduceError, "reduceError");
var jsonError = /* @__PURE__ */ __name(async (request, env, _ctx, middlewareCtx) => {
  try {
    return await middlewareCtx.next(request, env);
  } catch (e) {
    const error = reduceError(e);
    return Response.json(error, {
      status: 500,
      headers: { "MF-Experimental-Error-Stack": "true" }
    });
  }
}, "jsonError");
var middleware_miniflare3_json_error_default = jsonError;

// .wrangler/tmp/bundle-GMlCN8/middleware-insertion-facade.js
var __INTERNAL_WRANGLER_MIDDLEWARE__ = [
  middleware_ensure_req_body_drained_default,
  middleware_miniflare3_json_error_default
];
var middleware_insertion_facade_default = src_default;

// ../../../../../IDE/nvm/versions/node/v20.19.5/lib/node_modules/wrangler/templates/middleware/common.ts
var __facade_middleware__ = [];
function __facade_register__(...args) {
  __facade_middleware__.push(...args.flat());
}
__name(__facade_register__, "__facade_register__");
function __facade_invokeChain__(request, env, ctx, dispatch, middlewareChain) {
  const [head, ...tail] = middlewareChain;
  const middlewareCtx = {
    dispatch,
    next(newRequest, newEnv) {
      return __facade_invokeChain__(newRequest, newEnv, ctx, dispatch, tail);
    }
  };
  return head(request, env, ctx, middlewareCtx);
}
__name(__facade_invokeChain__, "__facade_invokeChain__");
function __facade_invoke__(request, env, ctx, dispatch, finalMiddleware) {
  return __facade_invokeChain__(request, env, ctx, dispatch, [
    ...__facade_middleware__,
    finalMiddleware
  ]);
}
__name(__facade_invoke__, "__facade_invoke__");

// .wrangler/tmp/bundle-GMlCN8/middleware-loader.entry.ts
var __Facade_ScheduledController__ = class ___Facade_ScheduledController__ {
  constructor(scheduledTime, cron, noRetry) {
    this.scheduledTime = scheduledTime;
    this.cron = cron;
    this.#noRetry = noRetry;
  }
  static {
    __name(this, "__Facade_ScheduledController__");
  }
  #noRetry;
  noRetry() {
    if (!(this instanceof ___Facade_ScheduledController__)) {
      throw new TypeError("Illegal invocation");
    }
    this.#noRetry();
  }
};
function wrapExportedHandler(worker) {
  if (__INTERNAL_WRANGLER_MIDDLEWARE__ === void 0 || __INTERNAL_WRANGLER_MIDDLEWARE__.length === 0) {
    return worker;
  }
  for (const middleware of __INTERNAL_WRANGLER_MIDDLEWARE__) {
    __facade_register__(middleware);
  }
  const fetchDispatcher = /* @__PURE__ */ __name(function(request, env, ctx) {
    if (worker.fetch === void 0) {
      throw new Error("Handler does not export a fetch() function.");
    }
    return worker.fetch(request, env, ctx);
  }, "fetchDispatcher");
  return {
    ...worker,
    fetch(request, env, ctx) {
      const dispatcher = /* @__PURE__ */ __name(function(type, init) {
        if (type === "scheduled" && worker.scheduled !== void 0) {
          const controller = new __Facade_ScheduledController__(
            Date.now(),
            init.cron ?? "",
            () => {
            }
          );
          return worker.scheduled(controller, env, ctx);
        }
      }, "dispatcher");
      return __facade_invoke__(request, env, ctx, dispatcher, fetchDispatcher);
    }
  };
}
__name(wrapExportedHandler, "wrapExportedHandler");
function wrapWorkerEntrypoint(klass) {
  if (__INTERNAL_WRANGLER_MIDDLEWARE__ === void 0 || __INTERNAL_WRANGLER_MIDDLEWARE__.length === 0) {
    return klass;
  }
  for (const middleware of __INTERNAL_WRANGLER_MIDDLEWARE__) {
    __facade_register__(middleware);
  }
  return class extends klass {
    #fetchDispatcher = /* @__PURE__ */ __name((request, env, ctx) => {
      this.env = env;
      this.ctx = ctx;
      if (super.fetch === void 0) {
        throw new Error("Entrypoint class does not define a fetch() function.");
      }
      return super.fetch(request);
    }, "#fetchDispatcher");
    #dispatcher = /* @__PURE__ */ __name((type, init) => {
      if (type === "scheduled" && super.scheduled !== void 0) {
        const controller = new __Facade_ScheduledController__(
          Date.now(),
          init.cron ?? "",
          () => {
          }
        );
        return super.scheduled(controller);
      }
    }, "#dispatcher");
    fetch(request) {
      return __facade_invoke__(
        request,
        this.env,
        this.ctx,
        this.#dispatcher,
        this.#fetchDispatcher
      );
    }
  };
}
__name(wrapWorkerEntrypoint, "wrapWorkerEntrypoint");
var WRAPPED_ENTRY;
if (typeof middleware_insertion_facade_default === "object") {
  WRAPPED_ENTRY = wrapExportedHandler(middleware_insertion_facade_default);
} else if (typeof middleware_insertion_facade_default === "function") {
  WRAPPED_ENTRY = wrapWorkerEntrypoint(middleware_insertion_facade_default);
}
var middleware_loader_entry_default = WRAPPED_ENTRY;
export {
  __INTERNAL_WRANGLER_MIDDLEWARE__,
  middleware_loader_entry_default as default
};
//# sourceMappingURL=index.js.map
