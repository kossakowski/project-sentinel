// Side-effect import FIRST: registers the notification handler and the headless
// background notification task in module scope, so they run at app load (incl.
// headless launches) before the React tree is registered. See bootstrap.ts (2.5/2.8).
import './src/notifications/bootstrap';

import { registerRootComponent } from 'expo';

import App from './App';

// registerRootComponent calls AppRegistry.registerComponent('main', () => App);
// It also ensures that whether you load the app in Expo Go or in a native build,
// the environment is set up appropriately
registerRootComponent(App);
