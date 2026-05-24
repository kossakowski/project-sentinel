import { StyleSheet, Text, View } from 'react-native';

export default function Original() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Sentinel</Text>
      <Text style={styles.subtitle}>Military Alert Monitor</Text>
      <Text style={styles.tag}>Stage A — Hello World</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fafaf7',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  title: {
    fontSize: 44,
    fontWeight: '300',
    letterSpacing: 2,
    color: '#1a1a1a',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: '#666',
    marginBottom: 32,
  },
  tag: {
    fontSize: 11,
    color: '#999',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
});
