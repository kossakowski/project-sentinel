/**
 * datetime helpers (3.11). `relative` boundaries are floors; `absolute` renders
 * device-local time — the absolute test pins TZ=Europe/Warsaw.
 */

import { relative, absolute } from '../datetime';

describe('relative', () => {
  const now = 1_700_000_000_000;

  test('test_datetime_relative', () => {
    expect(relative(new Date(now - 30_000).toISOString(), now)).toBe('now');
    expect(relative(new Date(now - 130_000).toISOString(), now)).toBe('2m');
    expect(relative(new Date(now - 3_600_000).toISOString(), now)).toBe('1h');
    expect(relative(new Date(now - 259_200_000).toISOString(), now)).toBe('3d');
  });

  test('floors at each boundary', () => {
    // 59s -> now; exactly 60s -> 1m; 59m59s -> 59m; exactly 60m -> 1h.
    expect(relative(new Date(now - 59_000).toISOString(), now)).toBe('now');
    expect(relative(new Date(now - 60_000).toISOString(), now)).toBe('1m');
    expect(relative(new Date(now - 3_599_000).toISOString(), now)).toBe('59m');
    expect(relative(new Date(now - 86_399_000).toISOString(), now)).toBe('23h');
    expect(relative(new Date(now - 86_400_000).toISOString(), now)).toBe('1d');
  });

  test('a future or unparseable timestamp renders "now"', () => {
    expect(relative(new Date(now + 10_000).toISOString(), now)).toBe('now');
    expect(relative('not-a-date', now)).toBe('now');
    expect(relative(null, now)).toBe('now');
  });
});

describe('absolute', () => {
  test('test_datetime_absolute_local', () => {
    const original = process.env.TZ;
    process.env.TZ = 'Europe/Warsaw';
    // 14:31 UTC on 2026-06-02 is 16:31 Warsaw (CEST, UTC+2).
    expect(absolute('2026-06-02T14:31:00Z')).toBe('2026-06-02 16:31');
    process.env.TZ = original;
  });

  test('handles missing / unparseable input', () => {
    expect(absolute(null)).toBe('—');
    expect(absolute(undefined)).toBe('—');
    expect(absolute('garbage')).toBe('garbage');
  });
});
