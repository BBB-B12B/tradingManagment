export type PositionStatus = "flat" | "long";

export interface PositionStatePayload {
  pair: string;
  status: PositionStatus;
  entryPrice?: number;
  entryTime?: string;
  wLow?: number;
  lastRulePassJson?: string;
  updatedAt: string;
}

export class PositionStateStore {
  constructor(private kvNamespace: KVNamespace) {}

  async get(pair: string): Promise<PositionStatePayload | null> {
    const data = await this.kvNamespace.get(pair, "json");
    return data as PositionStatePayload | null;
  }

  async put(state: PositionStatePayload): Promise<void> {
    await this.kvNamespace.put(state.pair, JSON.stringify(state));
  }
}
