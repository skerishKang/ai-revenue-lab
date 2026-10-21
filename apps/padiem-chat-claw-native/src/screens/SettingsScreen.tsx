import React, {useEffect, useState} from 'react';
import {Pressable, ScrollView, StyleSheet, Text, TextInput, View} from 'react-native';

import {currentBaseUrl, loadBaseUrl, setBaseUrl} from '../api/baseUrl';
import {TIER_LABELS} from '../api/types';
import {useAuth} from '../auth/AuthContext';
import {Locale, useLocale} from '../i18n/LocaleContext';import {PadiemTheme, radius, spacing, useTheme} from '../ui/theme';

/**
 * Settings.
 *
 * The account facts shown here (identity, member grade) come from the
 * server-verified session; the app never derives an entitlement locally.
 */
export function SettingsScreen(): React.JSX.Element {
  const theme = useTheme();
  const {strings, locale, setLocale} = useLocale();
  const {user, memberGrade, signedIn, signOut} = useAuth();

  const [baseUrl, setBaseUrlValue] = useState(currentBaseUrl());
  const [baseUrlDraft, setBaseUrlDraft] = useState(currentBaseUrl());
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void loadBaseUrl().then(value => {
      setBaseUrlValue(value);
      setBaseUrlDraft(value);
    });
  }, []);

  const identity =
    (user && (user.email ?? user.username ?? user.display_name)) || strings.guest;

  const handleSaveBaseUrl = async (): Promise<void> => {
    const next = await setBaseUrl(baseUrlDraft);
    setBaseUrlValue(next);
    setBaseUrlDraft(next);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const languages: Array<{value: Locale; label: string}> = [
    {value: 'ko', label: '한국어'},
    {value: 'en', label: 'English'},
  ];

  return (
    <ScrollView
      style={[styles.root, {backgroundColor: theme.background}]}
      contentContainerStyle={styles.content}>
      <Text style={[styles.title, {color: theme.text}]}>{strings.settingsTitle}</Text>

      <View
        style={[
          styles.card,
          {backgroundColor: theme.surface, borderColor: theme.border},
        ]}>
        <Text style={[styles.cardTitle, {color: theme.textMuted}]}>{strings.account}</Text>
        <Text style={[styles.value, {color: theme.text}]} numberOfLines={1}>
          {signedIn ? identity : strings.guest}
        </Text>
        <Text style={[styles.cardTitle, {color: theme.textMuted, marginTop: spacing.md}]}>
          {strings.member}
        </Text>
        <Text style={[styles.value, {color: theme.text}]}>
          {TIER_LABELS[memberGrade] ?? memberGrade}
        </Text>
      </View>

      <View
        style={[
          styles.card,
          {backgroundColor: theme.surface, borderColor: theme.border},
        ]}>
        <Text style={[styles.cardTitle, {color: theme.textMuted}]}>{strings.language}</Text>
        <View style={styles.row}>
          {languages.map(item => {
            const active = item.value === locale;
            return (
              <Pressable
                key={item.value}
                accessibilityRole="button"
                onPress={() => setLocale(item.value)}
                style={[
                  styles.pill,
                  {
                    backgroundColor: active ? theme.accentSoft : theme.surfaceRaised,
                    borderColor: active ? theme.accent : theme.border,
                  },
                ]}>
                <Text
                  style={[
                    styles.pillText,
                    {color: active ? theme.accent : theme.textMuted},
                  ]}>
                  {item.label}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      <View
        style={[
          styles.card,
          {backgroundColor: theme.surface, borderColor: theme.border},
        ]}>
        <Text style={[styles.cardTitle, {color: theme.textMuted}]}>
          {strings.apiBaseUrl}
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
          value={baseUrlDraft}
          onChangeText={setBaseUrlDraft}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          placeholder="https://chat.padiem.net"
          placeholderTextColor={theme.textMuted}
        />
        <View style={styles.row}>
          <Pressable
            accessibilityRole="button"
            onPress={() => void handleSaveBaseUrl()}
            style={[styles.button, {backgroundColor: theme.accent}]}>
            <Text style={styles.buttonLabel}>{strings.confirm}</Text>
          </Pressable>
          {saved ? (
            <Text style={[styles.saved, {color: theme.success}]}>✓</Text>
          ) : null}
        </View>
        <Text style={[styles.hint, {color: theme.textMuted}]}>{baseUrl}</Text>
      </View>

      {signedIn ? (
        <Pressable
          accessibilityRole="button"
          onPress={() => void signOut()}
          style={[styles.signOut, {borderColor: theme.danger}]}>
          <Text style={[styles.signOutLabel, {color: theme.danger}]}>
            {strings.signOut}
          </Text>
        </Pressable>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1},
  content: {padding: spacing.md, paddingBottom: spacing.xxl},
  title: {fontSize: 20, fontWeight: '700', marginBottom: spacing.lg},
  card: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  cardTitle: {fontSize: 11, letterSpacing: 0.4, marginBottom: 6},
  value: {fontSize: 15},
  row: {flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap'},
  pill: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    marginRight: spacing.sm,
  },
  pillText: {fontSize: 13, fontWeight: '600'},
  input: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    fontSize: 14,
    marginBottom: spacing.md,
  },
  button: {
    borderRadius: radius.pill,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  buttonLabel: {color: '#0b1020', fontWeight: '700', fontSize: 13},
  saved: {marginLeft: spacing.md, fontSize: 14},
  hint: {fontSize: 11, marginTop: spacing.md},
  signOut: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingVertical: spacing.md,
    alignItems: 'center',
    marginTop: spacing.sm,
  },
  signOutLabel: {fontSize: 15, fontWeight: '700'},
});
