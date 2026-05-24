import { Platform, StyleSheet, Text, View } from 'react-native';

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
};

const BLOBS: Blob[] = [
  { top: -20, left: -40, w: 170, h: 120, color: PALETTE.black,      rotate: 14,  rTL: 70, rTR: 50, rBR: 80, rBL: 45 },
  { top: 0,   left: 150, w: 140, h: 100, color: PALETTE.darkForest, rotate: -22, rTL: 55, rTR: 75, rBR: 50, rBL: 70 },
  { top: 30,  left: 270, w: 130, h: 95,  color: PALETTE.black,      rotate: 8,   rTL: 60, rTR: 45, rBR: 70, rBL: 55 },
  { top: 80,  left: -50, w: 130, h: 100, color: PALETTE.darkForest, rotate: -15, rTL: 50, rTR: 70, rBR: 45, rBL: 65 },
  { top: 100, left: 80,  w: 120, h: 90,  color: PALETTE.khaki,      rotate: 22,  rTL: 60, rTR: 50, rBR: 65, rBL: 45 },
  { top: 130, left: 210, w: 150, h: 105, color: PALETTE.darkForest, rotate: -10, rTL: 70, rTR: 55, rBR: 60, rBL: 75 },
  { top: 180, left: -30, w: 140, h: 100, color: PALETTE.black,      rotate: 12,  rTL: 55, rTR: 70, rBR: 50, rBL: 60 },
  { top: 210, left: 130, w: 130, h: 95,  color: PALETTE.midGreen,   rotate: -18, rTL: 60, rTR: 45, rBR: 70, rBL: 55 },
  { top: 240, left: 250, w: 140, h: 105, color: PALETTE.darkForest, rotate: 6,   rTL: 50, rTR: 75, rBR: 55, rBL: 65 },
  { top: 290, left: 30,  w: 150, h: 110, color: PALETTE.black,      rotate: -22, rTL: 70, rTR: 55, rBR: 60, rBL: 75 },
  { top: 330, left: 180, w: 120, h: 90,  color: PALETTE.khaki,      rotate: 16,  rTL: 55, rTR: 65, rBR: 45, rBL: 60 },
  { top: 370, left: -40, w: 130, h: 100, color: PALETTE.darkForest, rotate: -8,  rTL: 60, rTR: 50, rBR: 70, rBL: 55 },
  { top: 400, left: 100, w: 140, h: 100, color: PALETTE.black,      rotate: 20,  rTL: 50, rTR: 70, rBR: 55, rBL: 65 },
  { top: 440, left: 240, w: 130, h: 95,  color: PALETTE.midGreen,   rotate: -14, rTL: 65, rTR: 50, rBR: 60, rBL: 70 },
  { top: 490, left: -20, w: 150, h: 110, color: PALETTE.darkForest, rotate: 10,  rTL: 55, rTR: 75, rBR: 60, rBL: 50 },
  { top: 520, left: 150, w: 130, h: 100, color: PALETTE.black,      rotate: -18, rTL: 70, rTR: 55, rBR: 50, rBL: 65 },
  { top: 570, left: 260, w: 140, h: 100, color: PALETTE.darkForest, rotate: 8,   rTL: 60, rTR: 50, rBR: 70, rBL: 55 },
  { top: 610, left: 20,  w: 130, h: 95,  color: PALETTE.khaki,      rotate: 22,  rTL: 55, rTR: 70, rBR: 45, rBL: 60 },
  { top: 650, left: 130, w: 150, h: 110, color: PALETTE.black,      rotate: -10, rTL: 70, rTR: 55, rBR: 65, rBL: 50 },
  { top: 690, left: 260, w: 130, h: 95,  color: PALETTE.darkForest, rotate: 14,  rTL: 50, rTR: 65, rBR: 70, rBL: 55 },
  { top: 730, left: -30, w: 140, h: 100, color: PALETTE.black,      rotate: -20, rTL: 65, rTR: 55, rBR: 60, rBL: 70 },
  { top: 770, left: 120, w: 130, h: 95,  color: PALETTE.midGreen,   rotate: 10,  rTL: 55, rTR: 70, rBR: 50, rBL: 60 },
];

function Camo() {
  return (
    <View style={styles.camo} pointerEvents="none">
      {BLOBS.map((b, i) => (
        <View
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
            transform: [{ rotate: `${b.rotate}deg` }],
          }}
        />
      ))}
    </View>
  );
}

export default function Moro() {
  return (
    <View style={styles.container}>
      <Camo />

      <View style={styles.header}>
        <Text style={styles.headerText}>PL // SENTINEL // 01</Text>
        <Text style={styles.headerText}>wz. 2026</Text>
      </View>

      <View style={styles.center}>
        <View style={styles.stencilBand}>
          <Text style={styles.callsign}>SENTINEL</Text>
        </View>
        <View style={styles.subtitleBand}>
          <Text style={styles.subtitle}>SYGNALIZATOR ZAGROŻEŃ MILITARNYCH</Text>
        </View>
        <View style={styles.rule} />
        <View style={styles.subtitleBand}>
          <Text style={styles.body}>POLSKA  ·  LITWA  ·  ŁOTWA  ·  ESTONIA</Text>
        </View>
      </View>

      <View style={styles.footer}>
        <View style={styles.stamp}>
          <Text style={styles.stampText}>ZATWIERDZONO</Text>
        </View>
        <Text style={styles.footerSig}>— PROJECT SENTINEL —</Text>
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
    marginBottom: 8,
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
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  stencilBand: {
    backgroundColor: 'rgba(12, 14, 10, 0.85)',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderWidth: 1.5,
    borderColor: PALETTE.ivory,
    marginBottom: 18,
  },
  callsign: {
    color: PALETTE.ivory,
    fontSize: 42,
    fontFamily: STENCIL,
    fontWeight: '900',
    letterSpacing: 6,
    textAlign: 'center',
  },
  subtitleBand: {
    backgroundColor: 'rgba(12, 14, 10, 0.7)',
    paddingHorizontal: 12,
    paddingVertical: 5,
    marginBottom: 14,
  },
  subtitle: {
    color: PALETTE.ivory,
    fontSize: 11,
    fontFamily: SANS_BOLD,
    letterSpacing: 4,
    textAlign: 'center',
  },
  rule: {
    width: 60,
    height: 2,
    backgroundColor: PALETTE.ivory,
    marginBottom: 14,
    opacity: 0.7,
  },
  body: {
    color: PALETTE.ivory,
    fontSize: 12,
    fontFamily: MONO,
    letterSpacing: 2,
    textAlign: 'center',
  },
  footer: {
    alignItems: 'center',
  },
  stamp: {
    borderWidth: 2,
    borderColor: PALETTE.red,
    paddingHorizontal: 14,
    paddingVertical: 6,
    transform: [{ rotate: '-6deg' }],
    marginBottom: 12,
    backgroundColor: 'rgba(12, 14, 10, 0.8)',
  },
  stampText: {
    color: PALETTE.red,
    fontSize: 11,
    fontFamily: STENCIL,
    fontWeight: '900',
    letterSpacing: 2,
  },
  footerSig: {
    color: PALETTE.ivory,
    fontSize: 9,
    fontFamily: MONO,
    letterSpacing: 3,
    paddingHorizontal: 8,
    paddingVertical: 3,
    backgroundColor: 'rgba(12, 14, 10, 0.7)',
    borderRadius: 3,
  },
});
