/** Pure tap-routing decision (3.4). */

import { decideRoute } from '../routing';

describe('decideRoute', () => {
  test('test_decide_route_navigates_on_new_message', () => {
    expect(decideRoute('m1', null)).toEqual({
      navigate: true,
      messageId: 'm1',
      handledMessageId: 'm1',
    });
  });

  test('test_decide_route_dedupes_same_message', () => {
    expect(decideRoute('m1', 'm1')).toEqual({ navigate: false });
  });

  test('navigates for a different message than last handled', () => {
    expect(decideRoute('m2', 'm1')).toEqual({
      navigate: true,
      messageId: 'm2',
      handledMessageId: 'm2',
    });
  });

  test('does not navigate for a missing/empty messageId', () => {
    expect(decideRoute(null, null)).toEqual({ navigate: false });
    expect(decideRoute(undefined, 'm1')).toEqual({ navigate: false });
    expect(decideRoute('', null)).toEqual({ navigate: false });
  });
});
