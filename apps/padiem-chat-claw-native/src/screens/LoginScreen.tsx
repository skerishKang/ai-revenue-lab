import React, {useState} from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import {useAuth} from '../auth/AuthContext';
import {useLocale} from '../i18n/LocaleContext';
import {useTheme, radius, spacing} from '../ui/theme';

/**
 * Sign-in screen.
 *
 * Two entry points, both backed by the existing server contract: the Google
 * browser handoff and the password route. The app never implements an
 * authentication rule of its own.
 */
export function LoginScreen(): React.JSX.Element {
  const theme = useTheme();
  const {strings} = useLocale();
  const {handoff, error, signInWithGoogle, signInWithPassword, clearHandoff} = useAuth();

  const [passwordMode, setPasswordMode] = useState(false);
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const handleGoogle = async (): Promise<void> => {
    setBusy(true);
    setLocalError(null);
    try {
      await signInWithGoogle();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : strings.unknownError);
    } finally {
      setBusy(false);
    }
  };

  const handlePassword = async (): Promise<void> => {
    if (!identifier.trim() || !password) {
      return;
    }
    setBusy(true);
    setLocalError(null);
    try {
      await signInWithPassword(identifier.trim(), password);
      setPassword('');
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : strings.unknownError);
    } finally {
      setBusy(false);
    }
  };

  const message = localError ?? error;

  return (
    <KeyboardAvoidingView
      style={[styles.root, {backgroundColor: theme.background}]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        keyboardShouldPersistTaps="handled">
        <Text style={[styles.brand, {color: theme.text}]}>{strings.appName}</Text>
        <Text style={[styles.title, {color: theme.text}]}>{strings.signInTitle}</Text>
        <Text style={[styles.subtitle, {color: theme.textMuted}]}>
          {strings.signInSubtitle}
        </Text>

        {handoff ? (
          <View
            style={[
              styles.handoff,
              {backgroundColor: theme.surface, borderColor: theme.border},
            ]}>
            <Text style={[styles.handoffTitle, {color: theme.text}]}>
              {strings.handoffTitle}
            </Text>
            <Text style={[styles.handoffBody, {color: theme.textMuted}]}>
              {strings.handoffInstructions}
            </Text>
            <Text
              style={[
                styles.code,
                {color: theme.accent, backgroundColor: theme.accentSoft},
              ]}>
              {handoff.userCode}
            </Text>
            <Text style={[styles.handoffStatus, {color: theme.textMuted}]}>
              {handoff.status === 'awaiting_login'
                ? strings.handoffPending
                : handoff.status === 'awaiting_confirmation'
                  ? strings.handoffStatus
                  : handoff.status === 'ready'
                    ? strings.handoffReady
                    : handoff.status === 'expired'
                      ? strings.handoffExpired
                      : strings.handoffStatus}
            </Text>
            <Pressable
              accessibilityRole="button"
              onPress={clearHandoff}
              style={styles.linkButton}>
              <Text style={[styles.link, {color: theme.textMuted}]}>
                {strings.cancel}
              </Text>
            </Pressable>
          </View>
        ) : null}

        {message ? (
          <Text style={[styles.error, {color: theme.danger}]}>{message}</Text>
        ) : null}

        {passwordMode ? (
          <View style={styles.form}>
            <Text style={[styles.label, {color: theme.textMuted}]}>
              {strings.identifierLabel}
            </Text>
            <TextInput
              style={[
                styles.input,
                {
                  backgroundColor: theme.surfaceRaised,
                  borderColor: theme.border,
                  color: theme.text,
                },
              ]}
              value={identifier}
              onChangeText={setIdentifier}
              placeholder={strings.identifierLabel}
              placeholderTextColor={theme.textMuted}
              autoCapitalize="none"
              autoCorrect={false}
              editable={!busy}
            />
            <Text style={[styles.label, {color: theme.textMuted}]}>
              {strings.passwordLabel}
            </Text>
            <TextInput
              style={[
                styles.input,
                {
                  backgroundColor: theme.surfaceRaised,
                  borderColor: theme.border,
                  color: theme.text,
                },
              ]}
              value={password}
              onChangeText={setPassword}
              placeholder={strings.passwordLabel}
              placeholderTextColor={theme.textMuted}
              secureTextEntry
              autoCapitalize="none"
              editable={!busy}
              onSubmitEditing={() => void handlePassword()}
            />
            <Pressable
              accessibilityRole="button"
              disabled={busy}
              onPress={() => void handlePassword()}
              style={[styles.primary, {backgroundColor: theme.accent}]}>
              {busy ? (
                <ActivityIndicator color="#0b1020" />
              ) : (
                <Text style={styles.primaryLabel}>{strings.signIn}</Text>
              )}
            </Pressable>
            <Pressable
              accessibilityRole="button"
              onPress={() => setPasswordMode(false)}>
              <Text style={[styles.link, {color: theme.textMuted, textAlign: 'center'}]}>
                {strings.signInWithGoogle}
              </Text>
            </Pressable>
          </View>
        ) : (
          <Pressable
            accessibilityRole="button"
            disabled={busy}
            onPress={() => void handleGoogle()}
            style={[styles.primary, {backgroundColor: theme.accent}]}>
            {busy ? (
              <ActivityIndicator color="#0b1020" />
            ) : (
              <Text style={styles.primaryLabel}>{strings.signInWithGoogle}</Text>
            )}
          </Pressable>
        )}

        {!passwordMode ? (
          <Pressable
            accessibilityRole="button"
            onPress={() => setPasswordMode(true)}
            style={styles.linkButton}>
            <Text style={[styles.link, {color: theme.textMuted}]}>
              {strings.signInWithPassword}
            </Text>
          </Pressable>
        ) : null}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1},
  scroll: {flexGrow: 1, justifyContent: 'center', padding: spacing.xl},
  brand: {fontSize: 13, letterSpacing: 3, fontWeight: '700', marginBottom: spacing.lg},
  title: {fontSize: 26, fontWeight: '700', marginBottom: spacing.sm},
  subtitle: {fontSize: 14, lineHeight: 21, marginBottom: spacing.xl},
  handoff: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.lg,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  handoffTitle: {fontSize: 15, fontWeight: '700', marginBottom: 4},
  handoffBody: {fontSize: 13, lineHeight: 19},
  code: {
    fontSize: 24,
    fontWeight: '700',
    letterSpacing: 4,
    textAlign: 'center',
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    marginTop: spacing.md,
  },
  handoffStatus: {fontSize: 12, marginTop: spacing.md, textAlign: 'center'},
  form: {marginBottom: spacing.md},
  label: {fontSize: 12, marginBottom: 6, marginTop: spacing.md},
  input: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    fontSize: 15,
    marginBottom: spacing.sm,
  },
  primary: {
    borderRadius: radius.pill,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: spacing.md,
  },
  primaryLabel: {color: '#0b1020', fontWeight: '700', fontSize: 15},
  linkButton: {marginTop: spacing.lg, alignItems: 'center'},
  link: {fontSize: 13},
  error: {fontSize: 13, marginBottom: spacing.md},
});
