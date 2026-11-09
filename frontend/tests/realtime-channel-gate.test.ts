import assert from 'node:assert/strict';
import test from 'node:test';
import type { Page, WebSocketRoute } from '@playwright/test';
import { ChannelTimeoutError, createChannelGate } from '../e2e/channel.ts';

async function fixture() {
  let handshake: (socket: WebSocketRoute) => void = () => {};
  let now = 10;
  const page = {
    route: async () => {},
    routeWebSocket: async (_pattern: unknown, handler: typeof handshake) => { handshake = handler; },
    on: () => {}, off: () => {}, unroute: async () => {},
  } as unknown as Page;
  const gate = createChannelGate(page, { now: () => now });
  await gate.install();
  return {
    gate,
    attempt(at: number) {
      now = at;
      const calls = { connected: 0, closed: 0 };
      handshake({
        url: () => 'ws://localhost:8000/socket.io/?transport=websocket',
        connectToServer: () => { calls.connected += 1; },
        close: async () => { calls.closed += 1; },
      } as unknown as WebSocketRoute);
      return calls;
    },
  };
}

test('WebSocket-only attempts are counted and abort never connects to the server', async () => {
  const { gate, attempt } = await fixture();
  const live = attempt(10);
  assert.equal(live.connected, 1);
  gate.setMode('abort');
  await gate.closeEstablishedTransport();
  assert.equal(live.closed, 1);
  const blocked = attempt(20);
  assert.equal(blocked.connected, 0);
  assert.equal(blocked.closed, 1);
  assert.equal(gate.requests().length, 0);
  assert.deepEqual(gate.counts(), { established: 1, attempts: 2, blocked: 1, held: 0, rejectedHandshakes: 1 });
  assert.equal(await gate.waitForChannelRequestAfter(15, 10), 20);
  await gate.dispose();
});

test('hold keeps each manual WebSocket attempt pending until explicit release', async () => {
  const { gate, attempt } = await fixture();
  for (const at of [20, 30]) {
    gate.setMode('hold');
    const pending = gate.waitForChannelRequestAfter(at, 100);
    const socket = attempt(at);
    assert.equal(await pending, at);
    assert.equal(socket.connected, 0);
    assert.equal(socket.closed, 0);
    assert.equal(gate.counts().held, 1);
    await gate.releaseHeld();
    assert.equal(socket.closed, 1);
    assert.equal(gate.counts().held, 0);
    assert.equal(gate.isBlocked(), true);
  }
  await gate.unblock();
  const recovered = attempt(40);
  assert.equal(recovered.connected, 1);
  assert.equal(gate.counts().attempts, 3);
  assert.equal(gate.counts().blocked, 2);
  await gate.dispose();
});

test('an absent channel attempt still times out instead of inventing activity', async () => {
  const { gate } = await fixture();
  await assert.rejects(gate.waitForChannelRequestAfter(20, 1), ChannelTimeoutError);
  assert.equal(gate.counts().attempts, 0);
  await gate.dispose();
});
