// Shared React Router v7 future flags.
//
// Production (`main.tsx`) and every test rig that mounts a `<MemoryRouter>`
// or `<BrowserRouter>` should opt into these flags so they behave identically
// to the eventual v7 default and so the test output isn't cluttered with
// noisy "future flag warning" messages (F15).
export const routerFutureFlags = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
} as const;
