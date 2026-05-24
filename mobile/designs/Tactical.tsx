import { useEffect, useRef } from 'react';
import { Animated, Platform, StyleSheet, Text, View } from 'react-native';

const MONO = Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' });
const SANS_BOLD = Platform.select({ ios: 'Helvetica-Bold', android: 'sans-serif-black', default: 'System' });

const GREEN = '#3dff9a';
const RED = '#ff2e4a';
const DIM = '#5a5a5a';
const TEXT = '#e8e8e8';
const BG = '#0a0a0a';

export default function Tactical() {
  const blink = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(blink, { toValue: 0.3, duration: 700, useNativeDriver: true }),
        Animated.timing(blink, { toValue: 1, duration: 700, useNativeDriver: true }),
      ])
    ).start();
  }, [blink]);

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerLeft}>SENTINEL // OP-PL-01</Text>
        <View style={styles.headerRight}>
          <Animated.Text style={[styles.statusBlink, { opacity: blink }]}>●</Animated.Text>
          <Text style={styles.headerStatus}> ACTIVE</Text>
        </View>
      </View>
      <View style={styles.divider} />

      <View style={styles.crosshair}>
        <View style={styles.crossH} />
        <View style={styles.crossV} />
      </View>

      <View style={styles.center}>
        <Text style={styles.callsign}>SENTINEL</Text>
        <Text style={styles.mission}>BALTIC THREAT MONITOR</Text>
      </View>

      <View style={styles.spacer} />

      <View style={styles.bottomGrid}>
        <View style={styles.gridCell}>
          <Text style={styles.gridLabel}>SECTOR</Text>
          <Text style={styles.gridValue}>PL · LT · LV · EE</Text>
        </View>
        <View style={styles.gridCellRight}>
          <Text style={styles.gridLabel}>STATUS</Text>
          <Text style={styles.gridValueAccent}>NOMINAL</Text>
        </View>
      </View>
      <View style={styles.bottomGrid}>
        <View style={styles.gridCell}>
          <Text style={styles.gridLabel}>SOURCES</Text>
          <Text style={styles.gridValue}>47/47</Text>
        </View>
        <View style={styles.gridCellRight}>
          <Text style={styles.gridLabel}>THREAT</Text>
          <Text style={styles.gridValue}>LVL 1</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: BG,
    paddingHorizontal: 20,
    paddingTop: 60,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  headerLeft: {
    color: DIM,
    fontSize: 10,
    fontFamily: MONO,
    letterSpacing: 1.5,
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  statusBlink: {
    color: GREEN,
    fontSize: 10,
    fontFamily: MONO,
  },
  headerStatus: {
    color: GREEN,
    fontSize: 10,
    fontFamily: MONO,
    letterSpacing: 1.5,
  },
  divider: {
    height: 1,
    backgroundColor: '#222',
    marginBottom: 60,
  },
  crosshair: {
    height: 60,
    alignItems: 'center',
    justifyContent: 'center',
  },
  crossH: {
    position: 'absolute',
    width: 28,
    height: 1,
    backgroundColor: GREEN,
    opacity: 0.5,
  },
  crossV: {
    position: 'absolute',
    width: 1,
    height: 28,
    backgroundColor: GREEN,
    opacity: 0.5,
  },
  center: {
    alignItems: 'center',
    marginTop: 20,
  },
  callsign: {
    color: TEXT,
    fontSize: 52,
    fontFamily: SANS_BOLD,
    fontWeight: '900',
    letterSpacing: 8,
    marginBottom: 10,
  },
  mission: {
    color: RED,
    fontSize: 11,
    fontFamily: MONO,
    letterSpacing: 4,
  },
  spacer: { flex: 1 },
  bottomGrid: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: '#222',
    paddingVertical: 14,
  },
  gridCell: {
    flex: 1,
  },
  gridCellRight: {
    flex: 1,
    alignItems: 'flex-end',
  },
  gridLabel: {
    color: DIM,
    fontSize: 9,
    fontFamily: MONO,
    letterSpacing: 1.5,
    marginBottom: 6,
  },
  gridValue: {
    color: TEXT,
    fontSize: 13,
    fontFamily: MONO,
    letterSpacing: 1,
  },
  gridValueAccent: {
    color: GREEN,
    fontSize: 13,
    fontFamily: MONO,
    letterSpacing: 1,
  },
});
