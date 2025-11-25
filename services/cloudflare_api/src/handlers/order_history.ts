export async function logOrderHistory(env: Env, payload: any) {
  const stmt = env.CDC_DB.prepare(
    `INSERT INTO order_history (pair, order_type, amount, price, status, pnl, reason, rule_snapshot_json)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)`
  );
  await stmt.bind(
    payload.pair,
    payload.order_type,
    payload.amount,
    payload.price,
    payload.status,
    payload.pnl ?? null,
    payload.reason ?? null,
    JSON.stringify(payload.rule_snapshot ?? {}),
  ).run();
}
