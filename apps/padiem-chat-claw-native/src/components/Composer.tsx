import React, {useCallback, useState} from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import {pick, types} from '@react-native-documents/picker';

import {PadiemTheme, radius, spacing} from '../ui/theme';

export interface PickedAttachment {
  name: string;
  mimeType: string;
  uri: string;
  size: number | null;
}

interface Props {
  theme: PadiemTheme;
  value: string;
  onChangeText: (text: string) => void;
  onSend: () => void;
  onStop: () => void;
  onAttach: (attachment: PickedAttachment) => void;
  streaming: boolean;
  sending: boolean;
  disabled?: boolean;
  placeholder: string;
  sendLabel: string;
  stopLabel: string;
  attachLabel: string;
  micLabel: string;
  onMicPress?: () => void;
  micActive?: boolean;
  voiceHint?: string | null;
}

export function Composer({
  theme,
  value,
  onChangeText,
  onSend,
  onStop,
  onAttach,
  streaming,
  sending,
  disabled,
  placeholder,
  sendLabel,
  stopLabel,
  attachLabel,
  micLabel,
  onMicPress,
  micActive,
  voiceHint,
}: Props): React.JSX.Element {
  const [attachment, setAttachment] = useState<PickedAttachment | null>(null);
  const [picking, setPicking] = useState(false);

  const handleAttach = useCallback(async () => {
    try {
      setPicking(true);
      const [file] = await pick({
        type: [types.pdf, types.docx, types.xlsx, types.csv, types.plainText, types.images],
        allowMultiSelection: false,
      });
      if (!file) {
        return;
      }
      const picked: PickedAttachment = {
        name: file.name ?? 'attachment',
        mimeType: file.type ?? 'application/octet-stream',
        uri: file.uri,
        size: file.size ?? null,
      };
      setAttachment(picked);
      onAttach(picked);
    } catch (err) {
      const error = err as {code?: string; message?: string};
      if (error?.code === 'OPERATION_CANCELED' || error?.code === 'DOCUMENT_PICKER_CANCELED') {
        return;
      }
      // A cancelled or unavailable picker must not break the composer.
    } finally {
      setPicking(false);
    }
  }, [onAttach]);

  const busy = sending || streaming;

  return (
    <View
      style={[
        styles.container,
        {backgroundColor: theme.surface, borderTopColor: theme.border},
      ]}>
      {attachment && (
        <View style={[styles.attachmentRow, {borderColor: theme.border}]}>
          <Text style={[styles.attachmentName, {color: theme.text}]} numberOfLines={1}>
            {attachment.name}
          </Text>
          <Pressable
            accessibilityRole="button"
            onPress={() => setAttachment(null)}
            hitSlop={8}>
            <Text style={[styles.attachmentRemove, {color: theme.danger}]}>✕</Text>
          </Pressable>
        </View>
      )}
      {voiceHint ? (
        <Text style={[styles.voiceHint, {color: theme.accent}]}>{voiceHint}</Text>
      ) : null}
      <View style={styles.row}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={attachLabel}
          disabled={disabled || picking}
          onPress={() => {
            void handleAttach();
          }}
          style={[styles.iconButton, {borderColor: theme.border}]}>
          {picking ? (
            <ActivityIndicator size="small" color={theme.textMuted} />
          ) : (
            <Text style={[styles.icon, {color: theme.textMuted}]}>＋</Text>
          )}
        </Pressable>

        {onMicPress && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={micLabel}
            disabled={disabled}
            onPress={onMicPress}
            style={[
              styles.iconButton,
              {borderColor: theme.border},
              micActive ? {backgroundColor: theme.accentSoft} : null,
            ]}>
            <Text style={[styles.icon, {color: micActive ? theme.accent : theme.textMuted}]}>
              ●
            </Text>
          </Pressable>
        )}

        <TextInput
          style={[
            styles.input,
            {
              backgroundColor: theme.surfaceRaised,
              borderColor: theme.border,
              color: theme.text,
            },
          ]}
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor={theme.textMuted}
          multiline
          maxLength={8000}
          editable={!disabled}
        />

        {busy ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={stopLabel}
            onPress={onStop}
            style={[styles.sendButton, {backgroundColor: theme.danger}]}>
            <Text style={styles.sendLabelDark}>{stopLabel}</Text>
          </Pressable>
        ) : (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={sendLabel}
            disabled={disabled || value.trim().length === 0}
            onPress={onSend}
            style={[
              styles.sendButton,
              {
                backgroundColor:
                  value.trim().length === 0 ? theme.surfaceRaised : theme.accent,
              },
            ]}>
            <Text
              style={[
                styles.sendLabelDark,
                {color: value.trim().length === 0 ? theme.textMuted : '#0b1020'},
              ]}>
              {sendLabel}
            </Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
  },
  row: {flexDirection: 'row', alignItems: 'flex-end'},
  iconButton: {
    width: 40,
    height: 40,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.sm,
  },
  icon: {fontSize: 16},
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: 120,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: spacing.md,
    paddingTop: 10,
    paddingBottom: 10,
    fontSize: 15,
  },
  sendButton: {
    minWidth: 64,
    height: 40,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: spacing.sm,
    paddingHorizontal: spacing.md,
  },
  sendLabelDark: {fontSize: 14, fontWeight: '700'},
  attachmentRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginBottom: spacing.sm,
  },
  attachmentName: {fontSize: 13, flex: 1, marginRight: spacing.md},
  attachmentRemove: {fontSize: 14, fontWeight: '700'},
  voiceHint: {fontSize: 13, marginBottom: spacing.sm, paddingHorizontal: spacing.xs},
});
