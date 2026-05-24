import { Platform, StyleSheet, Text, View } from 'react-native';

const STENCIL = Platform.select({ ios: 'Stencil', android: 'sans-serif-condensed', default: 'System' });
const MONO = Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' });
const SANS_BOLD = Platform.select({ ios: 'HelveticaNeue-CondensedBold', android: 'sans-serif-condensed', default: 'System' });

const PALETTE = {
  base: '#d4dade',
  coolGrey: '#aeb6bb',
  slateBlue: '#6e8594',
  midBlue: '#587687',
  deepSlate: '#3f5a6c',
  ink: '#1f2a36',
  red: '#a8222b',
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
  { top: -20, left: -30, w: 160, h: 110, color: PALETTE.slateBlue, rotate: 14,  rTL: 70, rTR: 50, rBR: 80, rBL: 45 },
  { top: 10,  left: 140, w: 140, h: 100, color: PALETTE.coolGrey,  rotate: -20, rTL: 55, rTR: 75, rBR: 50, rBL: 70 },
  { top: 40,  left: 260, w: 130, h: 95,  color: PALETTE.deepSlate, rotate: 8,   rTL: 60, rTR: 45, rBR: 70, rBL: 55 },
  { top: 90,  left: -50, w: 130, h: 100, color: PALETTE.coolGrey,  rotate: -15, rTL: 50, rTR: 70, rBR: 45, rBL: 65 },
  { top: 110, left: 80,  w: 120, h: 90,  color: PALETTE.slateBlue, rotate: 22,  rTL: 60, rTR: 50, rBR: 65, rBL: 45 },
  { top: 140, left: 210, w: 150, h: 105, color: PALETTE.midBlue,   rotate: -10, rTL: 70, rTR: 55, rBR: 60, rBL: 75 },
  { top: 200, left: -30, w: 140, h: 100, color: PALETTE.deepSlate, rotate: 12,  rTL: 55, rTR: 70, rBR: 50, rBL: 60 },
  { top: 230, left: 130, w: 130, h: 95,  color: PALETTE.coolGrey,  rotate: -18, rTL: 60, rTR: 45, rBR: 70, rBL: 55 },
  { top: 260, left: 250, w: 140, h: 105, color: PALETTE.slateBlue, rotate: 6,   rTL: 50, rTR: 75, rBR: 55, rBL: 65 },
  { top: 310, left: 30,  w: 150, h: 110, color: PALETTE.midBlue,   rotate: -22, rTL: 70, rTR: 55, rBR: 60, rBL: 75 },
  { top: 350, left: 180, w: 120, h: 90,  color: PALETTE.deepSlate, rotate: 16,  rTL: 55, rTR: 65, rBR: 45, rBL: 60 },
  { top: 390, left: -40, w: 130, h: 100, color: PALETTE.coolGrey,  rotate: -8,  rTL: 60, rTR: 50, rBR: 70, rBL: 55 },
  { top: 420, left: 100, w: 140, h: 105, color: PALETTE.slateBlue, rotate: 20,  rTL: 50, rTR: 70, rBR: 55, rBL: 65 },
  { top: 460, left: 240, w: 130, h: 95,  color: PALETTE.coolGrey,  rotate: -14, rTL: 65, rTR: 50, rBR: 60, rBL: 70 },
  { top: 500, left: -20, w: 150, h: 110, color: PALETTE.midBlue,   rotate: 10,  rTL: 55, rTR: 75, rBR: 60, rBL: 50 },
  { top: 540, left: 150, w: 130, h: 100, color: PALETTE.deepSlate, rotate: -18, rTL: 70, rTR: 55, rBR: 50, rBL: 65 },
  { top: 580, left: 260, w: 140, h: 100, color: PALETTE.slateBlue, rotate: 8,   rTL: 60, rTR: 50, rBR: 70, rBL: 55 },
  { top: 620, left: 20,  w: 130, h: 95,  color: PALETTE.coolGrey,  rotate: 22,  rTL: 55, rTR: 70, rBR: 45, rBL: 60 },
  { top: 660, left: 130, w: 150, h: 110, color: PALETTE.slateBlue, rotate: -10, rTL: 70, rTR: 55, rBR: 65, rBL: 50 },
  { top: 700, left: 260, w: 130, h: 95,  color: PALETTE.deepSlate, rotate: 14,  rTL: 50, rTR: 65, rBR: 70, rBL: 55 },
  { top: 740, left: -30, w: 140, h: 100, color: PALETTE.midBlue,   rotate: -20, rTL: 65, rTR: 55, rBR: 60, rBL: 70 },
  { top: 780, left: 120, w: 130, h: 95,  color: PALETTE.coolGrey,  rotate: 10,  rTL: 55, rTR: 70, rBR: 50, rBL: 60 },
];

function ArcticCamo() {
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

export default function MoroArctic() {
  return (
    <View style={styles.container}>
      <ArcticCamo />

      <View style={styles.header}>
        <Text style={styles.headerText}>PL // SENTINEL // 01 — N</Text>
        <Text style={styles.headerText}>wz. ZIMA 2026</Text>
      </View>

      <View style={styles.center}>
        <View style={styles.stencilBand}>
          <Text style={styles.callsign}>SENTINEL</Text>
        </View>
        <View style={styles.subtitleBand}>
          <Text style={styles.subtitle}>FLANKA PÓŁNOCNA  ·  ZIMA</Text>
        </View>
        <View style={styles.rule} />
        <View style={styles.subtitleBand}>
          <Text style={styles.body}>ESTONIA  ·  ŁOTWA  ·  LITWA  ·  POLSKA</Text>
        </View>
      </View>

      <View style={styles.footer}>
        <View style={styles.stamp}>
          <Text style={styles.stampText}>ZATWIERDZONO</Text>
        </View>
        <Text style={styles.footerSig}>— PROJECT SENTINEL  ·  ARCTIC —</Text>
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
    backgroundColor: 'rgba(212, 218, 222, 0.8)',
    borderRadius: 4,
  },
  headerText: {
    color: PALETTE.ink,
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
    backgroundColor: 'rgba(31, 42, 54, 0.92)',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderWidth: 1.5,
    borderColor: PALETTE.base,
    marginBottom: 18,
  },
  callsign: {
    color: PALETTE.base,
    fontSize: 42,
    fontFamily: STENCIL,
    fontWeight: '900',
    letterSpacing: 6,
    textAlign: 'center',
  },
  subtitleBand: {
    backgroundColor: 'rgba(212, 218, 222, 0.85)',
    paddingHorizontal: 12,
    paddingVertical: 5,
    marginBottom: 14,
  },
  subtitle: {
    color: PALETTE.ink,
    fontSize: 11,
    fontFamily: SANS_BOLD,
    letterSpacing: 4,
    textAlign: 'center',
  },
  rule: {
    width: 60,
    height: 2,
    backgroundColor: PALETTE.ink,
    marginBottom: 14,
    opacity: 0.7,
  },
  body: {
    color: PALETTE.ink,
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
    backgroundColor: 'rgba(212, 218, 222, 0.85)',
  },
  stampText: {
    color: PALETTE.red,
    fontSize: 11,
    fontFamily: STENCIL,
    fontWeight: '900',
    letterSpacing: 2,
  },
  footerSig: {
    color: PALETTE.ink,
    fontSize: 9,
    fontFamily: MONO,
    letterSpacing: 3,
    paddingHorizontal: 8,
    paddingVertical: 3,
    backgroundColor: 'rgba(212, 218, 222, 0.8)',
    borderRadius: 3,
  },
});
