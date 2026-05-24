import { useState } from 'react';
import { Pressable, SafeAreaView, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import Original from './designs/Original';
import Moro from './designs/Moro';
import MoroActive from './designs/MoroActive';
import MoroArctic from './designs/MoroArctic';
import Tactical from './designs/Tactical';

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
  const [i, setI] = useState(0);
  const current = DESIGNS[i];
  const { Component, dark } = current;

  return (
    <View style={[styles.root, dark && styles.rootDark]}>
      <View style={styles.canvas}>
        <Component />
      </View>
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
        </View>
      </SafeAreaView>
      <StatusBar style={dark ? 'light' : 'dark'} />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#fff' },
  rootDark: { backgroundColor: '#0a0a0a' },
  canvas: { flex: 1 },
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
});
