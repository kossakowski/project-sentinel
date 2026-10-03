# Expo HAS CHANGED

Read the exact versioned docs at https://docs.expo.dev/versions/v54.0.0/ before writing any code.

Facts you need before you change anything in `mobile/` (details: [docs/explanation/mobile-app.md](../docs/explanation/mobile-app.md)):

- The app is live on the owner's iPhone as a standalone EAS `preview` build. A change reaches the
  phone only after `eas build --profile preview --platform ios` and a reinstall, so batch changes
  before rebuilding.
- Gates: `npm test` (jest-expo) and `npm run typecheck` must both pass.
- Add native modules with `npx expo install <pkg>` so versions match SDK 54. `.npmrc` sets
  `legacy-peer-deps=true` on purpose; read its comment before changing it.
- The push `data` contract (`PushPayload` in `src/messages/types.ts`) is coupled to the server
  builder `_build_push_data` in `sentinel/alerts/state_machine.py`. Never change one side without
  the other.
- The device push token lives on the server as `EXPO_PUSH_TOKEN` in `/etc/sentinel/sentinel.env`.
  Changing it is a production write and needs the owner's permission. Never put a token value in
  tracked config or code; the repo is public.
