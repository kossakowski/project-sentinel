import {
  parsePayload,
  parseForeground,
  parseHeadless,
} from '../parsePayload';
import type { PushPayload } from '../types';

const richPayload: PushPayload = {
  message_id: 'f3a9c1e27b8d4e10',
  event_id: 'evt_123',
  kind: 'event',
  event_type: 'missile_strike',
  event_type_pl: 'Uderzenie rakietowe',
  urgency_score: 9,
  affected_countries: ['PL'],
  aggressor: 'Rosja',
  summary_pl: 'Rosja wystrzeliła rakiety w kierunku Polski. (full, untrimmed)',
  sources: [
    { name: 'PAP', title: 'Atak rakietowy na Polskę', url: 'https://www.pap.pl/article/123' },
    { name: 'Reuters', title: 'Missiles fired toward Poland', url: 'https://reuters.com/world/x' },
  ],
  sms_body: 'SMS mirror text',
  first_seen_at: '2026-06-02T14:31:00Z',
};

describe('parsePayload', () => {
  test('test_parse_rich_payload', () => {
    const msg = parsePayload(richPayload, {
      title: '🚨 PROJECT SENTINEL: Uderzenie rakietowe',
      body: 'Rosja wystrzeliła rakiety.\nPilność 9/10 · źródła: 2',
    });

    expect(msg.message_id).toBe('f3a9c1e27b8d4e10');
    expect(msg.event_id).toBe('evt_123');
    expect(msg.kind).toBe('event');
    expect(msg.event_type).toBe('missile_strike');
    expect(msg.event_type_pl).toBe('Uderzenie rakietowe');
    expect(msg.urgency_score).toBe(9);
    expect(msg.affected_countries).toEqual(['PL']);
    expect(typeof msg.aggressor).toBe('string');
    expect(msg.aggressor).toBe('Rosja');
    expect(msg.summary_pl).toBe(richPayload.summary_pl);
    expect(msg.sources).toHaveLength(2);
    expect(msg.sources[0]).toEqual({
      name: 'PAP',
      title: 'Atak rakietowy na Polskę',
      url: 'https://www.pap.pl/article/123',
    });
    expect(msg.sms_body).toBe('SMS mirror text');
    expect(msg.first_seen_at).toBe('2026-06-02T14:31:00Z');
    expect(msg.read).toBe(false);
    expect(typeof msg.received_at).toBe('string');
    expect(msg.received_at.length).toBeGreaterThan(0);
  });

  test('test_parse_thin_payload_fallback', () => {
    const body = 'Wykryto zagrożenie wojskowe.';
    const msg = parsePayload(
      { event_id: 'evt_only' },
      { title: 'Tytuł pushy', body },
    );

    expect(msg.message_id).toBe('evt_only'); // fallback to event_id
    expect(msg.event_id).toBe('evt_only');
    expect(msg.sources).toEqual([]);
    expect(msg.sms_body).toBe(body);
    expect(msg.summary_pl).toBe(body);
    expect(msg.event_type_pl).toBe('Tytuł pushy'); // title fallback
    expect(msg.aggressor).toBe('');
  });

  test('test_parse_thin_payload_event_type_pl_alert_fallback', () => {
    // No event_type_pl and no title -> '(alert)'.
    const msg = parsePayload({ event_id: 'e' }, { title: null, body: null });
    expect(msg.event_type_pl).toBe('(alert)');
  });

  test('test_parse_null_title_body_synth_key', () => {
    const msg = parsePayload(undefined, { title: null, body: null });
    expect(msg.message_id).toMatch(/^synth:/);
    expect(msg.summary_pl).toBe('');
    expect(msg.sms_body).toBe('');
    expect(msg.sources).toEqual([]);
    expect(msg.aggressor).toBe('');
  });

  test('parsePayload uses osIdentifier before synth', () => {
    const msg = parsePayload({}, { title: null, body: null, osIdentifier: 'os-uuid-1' });
    expect(msg.message_id).toBe('os-uuid-1');
  });

  test('test_parse_headless_datastring_shape', () => {
    const headless = parseHeadless({ data: { dataString: JSON.stringify(richPayload) } });
    const foreground = parseForeground({
      request: { content: { title: null, body: null, data: richPayload } },
    });

    // Same parsed identity/fields (received_at differs since it's set per-call).
    expect(headless.message_id).toBe(foreground.message_id);
    expect(headless.summary_pl).toBe(foreground.summary_pl);
    expect(headless.sources).toEqual(foreground.sources);
    expect(headless.event_type_pl).toBe(foreground.event_type_pl);
  });

  test('test_parse_headless_malformed_shape_fallback', () => {
    expect(() => parseHeadless({ data: { dataString: 'not-json{' } })).not.toThrow();
    const msg = parseHeadless({ data: { dataString: 'not-json{' } });
    expect(msg.message_id).toMatch(/^synth:/);

    // Entirely missing shape — still no throw, still a usable message.
    expect(() => parseHeadless(undefined)).not.toThrow();
    expect(parseHeadless(undefined).message_id).toMatch(/^synth:/);
  });

  test('parseForeground null-guards an empty content.data', () => {
    const msg = parseForeground({
      request: { identifier: 'os-x', content: { title: 'T', body: 'B', data: {} } },
    });
    // No message_id/event_id in data -> fall back to osIdentifier.
    expect(msg.message_id).toBe('os-x');
    expect(msg.summary_pl).toBe('B');
  });
});
