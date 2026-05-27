import { useState } from 'react';
import { Pressable, SafeAreaView, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import Original from './designs/Original';
import Moro from './designs/Moro';
import MoroActive from './designs/MoroActive';
import MoroArctic from './designs/MoroArctic';
import Tactical from './designs/Tactical';
import PushPanel from './push/PushPanel';

type Design = {
  name: string;
  Component: () => React.JSX.Element;
  dark: boolean;
};

const DESIGNS: Design[] = [
  { name: 'Original', Component: Original, dark: false },
  { name: 'Moro', Component: Moro, dark: true },
  { name: 'Moro+', Component: MoroActive, dark: true },
  { name: 'Arctic', Component: MoroArctic, dark: false },
  { name: 'Tactical', Component: Tactical, dark: true },
];

export default function App() {
  const [i, setI] = useState(DESIGNS.findIndex((d) => d.name === 'Tactical'));
  const [showPush, setShowPush] = useState(false);
  const current = DESIGNS[i];
  const { Component, dark } = current;

  return (
    <View style={[styles.root, dark && styles.rootDark]}>
      <View style={styles.canvas}>
        <Component />
      </View>
      {showPush && (
        <View style={styles.overlay}>
          <PushPanel onClose={() => setShowPush(false)} />
        </View>
      )}
      <SafeAreaView style={[styles.pickerSafe, dark && styles.pickerSafeDark]}>
        <View style={[styles.picker, dark && styles.pickerDark]}>
          {DESIGNS.map((d, idx) => {
            const active = idx === i;
            return (
              <Pressable
                key={d.name}
                onPress={() => setI(idx)}
                style={[
                  styles.pill,
                  active && (dark ? styles.pillActiveDark : styles.pillActiveLight),
                ]}
              >
                <Text
                  style={[
                    styles.pillText,
                    dark ? styles.pillTextDark : styles.pillTextLight,
                    active && (dark ? styles.pillTextActiveDark : styles.pillTextActiveLight),
                  ]}
                >
                  {d.name}
                </Text>
              </Pressable>
            );
          })}
          <Pressable
            onPress={() => setShowPush((v) => !v)}
            style={[styles.pill, styles.pushPill, showPush && styles.pushPillActive]}
          >
            <Text
              style={[styles.pillText, showPush ? styles.pushPillTextActive : styles.pushPillText]}
            >
              PUSH
            </Text>
          </Pressable>
        </View>
      </SafeAreaView>
      <StatusBar style={dark || showPush ? 'light' : 'dark'} />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#fff' },
  rootDark: { backgroundColor: '#0a0a0a' },
  canvas: { flex: 1 },
  overlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: '#0a0a0a',
  },
  pickerSafe: { backgroundColor: '#fff' },
  pickerSafeDark: { backgroundColor: '#0a0a0a' },
  picker: {
    flexDirection: 'row',
    justifyContent: 'center',
    paddingVertical: 10,
    paddingHorizontal: 8,
    gap: 4,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#e0e0e0',
  },
  pickerDark: { borderTopColor: '#222' },
  pill: {
    paddingHorizontal: 10,
    paddingVertical: 7,
    borderRadius: 16,
    backgroundColor: 'transparent',
  },
  pillActiveLight: { backgroundColor: '#1a1a1a' },
  pillActiveDark: { backgroundColor: '#e8e8e8' },
  pillText: { fontSize: 11, letterSpacing: 0.3, fontWeight: '500' },
  pillTextLight: { color: '#888' },
  pillTextDark: { color: '#777' },
  pillTextActiveLight: { color: '#fff' },
  pillTextActiveDark: { color: '#0a0a0a' },
  pushPill: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#3dff9a',
  },
  pushPillActive: { backgroundColor: '#3dff9a' },
  pushPillText: { color: '#3dff9a' },
  pushPillTextActive: { color: '#0a0a0a', fontWeight: '700' },
});
