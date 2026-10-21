import React, {useState} from 'react';
import {Modal, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';

import {TIER_LABELS, TIER_ORDER, Tier} from '../api/types';
import {PadiemTheme, radius, spacing} from '../ui/theme';

interface Props {
  theme: PadiemTheme;
  tier: Tier;
  allowedTiers: Tier[];
  adminAvailable: boolean | null;
  disabled?: boolean;
  onSelect: (tier: Tier) => void;
  label: string;
}

/**
 * Model tier picker.
 *
 * The server owns which tiers an account may use (`allowed_tiers` /
 * `admin_available`); the app only ever offers the tiers the server already
 * authorised, and it never names a provider or a model id.
 */
export function TierPicker({
  theme,
  tier,
  allowedTiers,
  adminAvailable,
  disabled,
  onSelect,
  label,
}: Props): React.JSX.Element {
  const [open, setOpen] = useState(false);

  const options = TIER_ORDER.filter(item => allowedTiers.includes(item));
  if (adminAvailable === true && !options.includes('admin')) {
    options.push('admin');
  }

  const handlePress = (next: Tier): void => {
    setOpen(false);
    if (next !== tier) {
      onSelect(next);
    }
  };

  return (
    <View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={label}
        disabled={disabled}
        onPress={() => setOpen(true)}
        style={[
          styles.trigger,
          {backgroundColor: theme.surfaceRaised, borderColor: theme.border},
        ]}>
        <Text style={[styles.triggerLabel, {color: theme.textMuted}]}>{label}</Text>
        <Text style={[styles.triggerValue, {color: theme.text}]}>
          {TIER_LABELS[tier]}
        </Text>
        <Text style={[styles.caret, {color: theme.textMuted}]}>▾</Text>
      </Pressable>

      <Modal
        visible={open}
        transparent
        animationType="fade"
        onRequestClose={() => setOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setOpen(false)}>
          <View
            style={[
              styles.sheet,
              {backgroundColor: theme.surface, borderColor: theme.border},
            ]}>
            <Text style={[styles.sheetTitle, {color: theme.text}]}>{label}</Text>
            <ScrollView>
              {options.map(item => {
                const active = item === tier;
                return (
                  <Pressable
                    key={item}
                    accessibilityRole="button"
                    onPress={() => handlePress(item)}
                    style={[
                      styles.option,
                      {borderBottomColor: theme.border},
                    ]}>
                    <Text
                      style={[
                        styles.optionText,
                        {color: active ? theme.accent : theme.text},
                      ]}>
                      {TIER_LABELS[item]}
                    </Text>
                    {active && (
                      <Text style={[styles.check, {color: theme.accent}]}>✓</Text>
                    )}
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  trigger: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    marginRight: spacing.sm,
  },
  triggerLabel: {fontSize: 11, marginRight: 6},
  triggerValue: {fontSize: 13, fontWeight: '600'},
  caret: {fontSize: 11, marginLeft: 6},
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.55)',
    justifyContent: 'center',
    padding: spacing.xl,
  },
  sheet: {
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    paddingVertical: spacing.lg,
    maxHeight: '70%',
  },
  sheetTitle: {fontSize: 16, fontWeight: '700', paddingHorizontal: spacing.lg},
  option: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  optionText: {fontSize: 15},
  check: {fontSize: 15, fontWeight: '700'},
});
