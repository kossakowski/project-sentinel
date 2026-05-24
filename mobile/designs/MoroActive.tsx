import { useEffect, useRef, useState } from 'react';
import { Animated, Platform, StyleSheet, Text, View } from 'react-native';

const STENCIL = Platform.select({ ios: 'Stencil', android: 'sans-serif-condensed', default: 'System' });
const MONO = Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' });
const SANS_BOLD = Platform.select({ ios: 'HelveticaNeue-CondensedBold', android: 'sans-serif-condensed', default: 'System' });

const PALETTE = {
  base: '#4f6035',
  midGreen: '#3d4d2a',
  darkForest: '#2a3520',
  khaki: '#8a7a52',
  black: '#0c0e0a',
  ivory: '#e8e2cf',
  red: '#b8211a',
  amber: '#d99b1f',
};

type Blob = {
  top: number;
  left: number;
  w: number;
  h: number;
  color: string;
  rotate: number;
  rTL: number;
  rTR: number;
  rBR: number;
  rBL: number;
  drift: number;
};

const BLOBS: Blob[] = [
  { top: -20, left: -40, w: 170, h: 120, color: PALETTE.black,      rotate: 14,  rTL: 70, rTR: 50, rBR: 80, rBL: 45, drift: 8 },
  { top: 10,  left: 160, w: 140, h: 100, color: PALETTE.darkForest, rotate: -20, rTL: 55, rTR: 75, rBR: 50, rBL: 70, drift: -10 },
  { top: 40,  left: 280, w: 130, h: 95,  color: PALETTE.black,      rotate: 8,   rTL: 60, rTR: 45, rBR: 70, rBL: 55, drift: 6 },
  { top: 100, left: -50, w: 130, h: 100, color: PALETTE.darkForest, rotate: -15, rTL: 50, rTR: 70, rBR: 45, rBL: 65, drift: 8 },
  { top: 130, left: 90,  w: 120, h: 90,  color: PALETTE.khaki,      rotate: 22,  rTL: 60, rTR: 50, rBR: 65, rBL: 45, drift: -6 },
  { top: 160, left: 220, w: 150, h: 105, color: PALETTE.darkForest, rotate: -10, rTL: 70, rTR: 55, rBR: 60, rBL: 75, drift: 10 },
  { top: 220, left: -30, w: 140, h: 100, color: PALETTE.black,      rotate: 12,  rTL: 55, rTR: 70, rBR: 50, rBL: 60, drift: -8 },
  { top: 240, left: 140, w: 130, h: 95,  color: PALETTE.midGreen,   rotate: -18, rTL: 60, rTR: 45, rBR: 70, rBL: 55, drift: 6 },
  { top: 280, left: 260, w: 140, h: 105, color: PALETTE.darkForest, rotate: 6,   rTL: 50, rTR: 75, rBR: 55, rBL: 65, drift: -10 },
  { top: 330, left: 40,  w: 150, h: 110, color: PALETTE.black,      rotate: -22, rTL: 70, rTR: 55, rBR: 60, rBL: 75, drift: 8 },
  { top: 370, left: 190, w: 120, h: 90,  color: PALETTE.khaki,      rotate: 16,  rTL: 55, rTR: 65, rBR: 45, rBL: 60, drift: -6 },
  { top: 410, left: -40, w: 130, h: 100, color: PALETTE.darkForest, rotate: -8,  rTL: 60, rTR: 50, rBR: 70, rBL: 55, drift: 10 },
  { top: 440, left: 110, w: 140, h: 100, color: PALETTE.black,      rotate: 20,  rTL: 50, rTR: 70, rBR: 55, rBL: 65, drift: -8 },
  { top: 470, left: 250, w: 130, h: 95,  color: PALETTE.midGreen,   rotate: -14, rTL: 65, rTR: 50, rBR: 60, rBL: 70, drift: 6 },
  { top: 510, left: -20, w: 150, h: 110, color: PALETTE.darkForest, rotate: 10,  rTL: 55, rTR: 75, rBR: 60, rBL: 50, drift: -10 },
  { top: 540, left: 160, w: 130, h: 100, color: PALETTE.black,      rotate: -18, rTL: 70, rTR: 55, rBR: 50, rBL: 65, drift: 8 },
  { top: 580, left: 270, w: 140, h: 100, color: PALETTE.darkForest, rotate: 8,   rTL: 60, rTR: 50, rBR: 70, rBL: 55, drift: -8 },
  { top: 620, left: 30,  w: 130, h: 95,  color: PALETTE.khaki,      rotate: 22,  rTL: 55, rTR: 70, rBR: 45, rBL: 60, drift: 6 },
  { top: 660, left: 140, w: 150, h: 110, color: PALETTE.black,      rotate: -10, rTL: 70, rTR: 55, rBR: 65, rBL: 50, drift: -10 },
  { top: 700, left: 270, w: 130, h: 95,  color: PALETTE.darkForest, rotate: 14,  rTL: 50, rTR: 65, rBR: 70, rBL: 55, drift: 8 },
];

function DriftingCamo({ drift }: { drift: Animated.Value }) {
  return (
    <View style={styles.camo} pointerEvents="none">
      {BLOBS.map((b, i) => (
        <Animated.View
          key={i}
          style={{
            position: 'absolute',
            top: b.top,
            left: b.left,
            width: b.w,
            height: b.h,
            backgroundColor: b.color,
            borderTopLeftRadius: b.rTL,
            borderTopRightRadius: b.rTR,
            borderBottomRightRadius: b.rBR,
            borderBottomLeftRadius: b.rBL,
            transform: [
              { rotate: `${b.rotate}deg` },
              {
                translateX: drift.interpolate({
                  inputRange: [0, 1],
                  outputRange: [0, b.drift],
                }),
              },
            ],
          }}
        />
      ))}
    </View>
  );
}

export default function MoroActive() {
  const drift = useRef(new Animated.Value(0)).current;
  const alertPulse = useRef(new Animated.Value(0.4)).current;
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(drift, { toValue: 1, duration: 8000, useNativeDriver: true }),
        Animated.timing(drift, { toValue: 0, duration: 8000, useNativeDriver: true }),
      ])
    ).start();
  }, [drift]);

  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(alertPulse, { toValue: 1, duration: 600, useNativeDriver: true }),
        Animated.timing(alertPulse, { toValue: 0.4, duration: 600, useNativeDriver: true }),
      ])
    ).start();
  }, [alertPulse]);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const timeStr = now.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const dateStr = now.toLocaleDateString('pl-PL', { day: '2-digit', month: '2-digit', year: 'numeric' });

  return (
    <View style={styles.container}>
      <DriftingCamo drift={drift} />

      <View style={styles.header}>
        <Text style={styles.headerText}>PL // SENTINEL // 01</Text>
        <View style={styles.statusGroup}>
          <Animated.View style={[styles.statusDot, { opacity: alertPulse }]} />
          <Text style={styles.statusText}>AKTYWNY</Text>
        </View>
      </View>

      <View style={styles.center}>
        <View style={styles.stencilBand}>
          <Text style={styles.callsign}>SENTINEL</Text>
        </View>
        <View style={styles.subtitleBand}>
          <Text style={styles.subtitle}>POSTERUNEK CZYNNY</Text>
        </View>
      </View>

      <View style={styles.panel}>
        <View style={styles.panelRow}>
          <Text style={styles.panelLabel}>CZAS LOKALNY</Text>
          <Text style={styles.panelValueMono}>{timeStr}</Text>
        </View>
        <View style={styles.panelDivider} />
        <View style={styles.panelRow}>
          <Text style={styles.panelLabel}>DATA</Text>
          <Text style={styles.panelValueMono}>{dateStr}</Text>
        </View>
        <View style={styles.panelDivider} />
        <View style={styles.panelRow}>
          <Text style={styles.panelLabel}>POZIOM ZAGROŻENIA</Text>
          <Text style={styles.panelValueAccent}>1 — SPOKÓJ</Text>
        </View>
        <View style={styles.panelDivider} />
        <View style={styles.panelRow}>
          <Text style={styles.panelLabel}>NASŁUCH</Text>
          <Text style={styles.panelValueMono}>47 ŹRÓDEŁ</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: PALETTE.base,
    paddingHorizontal: 24,
    paddingTop: 56,
    paddingBottom: 24,
  },
  camo: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    overflow: 'hidden',
    backgroundColor: PALETTE.base,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
    paddingHorizontal: 8,
    paddingVertical: 4,
    backgroundColor: 'rgba(12, 14, 10, 0.7)',
    borderRadius: 4,
  },
  headerText: {
    color: PALETTE.ivory,
    fontSize: 10,
    fontFamily: MONO,
    letterSpacing: 1.5,
  },
  statusGroup: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: PALETTE.red,
    marginRight: 8,
  },
  statusText: {
    color: PALETTE.red,
    fontSize: 11,
    fontFamily: STENCIL,
    fontWeight: '900',
    letterSpacing: 2,
  },
  center: {
    alignItems: 'center',
    marginTop: 40,
    marginBottom: 36,
  },
  stencilBand: {
    backgroundColor: 'rgba(12, 14, 10, 0.85)',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderWidth: 1.5,
    borderColor: PALETTE.ivory,
    marginBottom: 16,
  },
  callsign: {
    color: PALETTE.ivory,
    fontSize: 40,
    fontFamily: STENCIL,
    fontWeight: '900',
    letterSpacing: 6,
    textAlign: 'center',
  },
  subtitleBand: {
    backgroundColor: 'rgba(12, 14, 10, 0.7)',
    paddingHorizontal: 12,
    paddingVertical: 5,
  },
  subtitle: {
    color: PALETTE.amber,
    fontSize: 11,
    fontFamily: SANS_BOLD,
    letterSpacing: 4,
    textAlign: 'center',
  },
  panel: {
    backgroundColor: 'rgba(12, 14, 10, 0.85)',
    borderWidth: 1,
    borderColor: 'rgba(232, 226, 207, 0.3)',
    padding: 16,
    marginTop: 'auto',
  },
  panelRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    paddingVertical: 6,
  },
  panelDivider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: 'rgba(232, 226, 207, 0.15)',
  },
  panelLabel: {
    color: PALETTE.ivory,
    opacity: 0.7,
    fontSize: 10,
    fontFamily: MONO,
    letterSpacing: 1.5,
  },
  panelValueMono: {
    color: PALETTE.ivory,
    fontSize: 13,
    fontFamily: MONO,
    letterSpacing: 1,
  },
  panelValueAccent: {
    color: PALETTE.amber,
    fontSize: 13,
    fontFamily: STENCIL,
    fontWeight: '900',
    letterSpacing: 1,
  },
});
