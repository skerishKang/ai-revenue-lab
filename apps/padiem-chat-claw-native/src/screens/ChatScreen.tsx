import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import {ChatMessage} from '../api/types';
import {ClawStatusBar} from '../components/ClawStatusBar';
import {Composer, PickedAttachment} from '../components/Composer';
import {MessageBubble} from '../components/MessageBubble';
import {Sidebar} from '../components/Sidebar';
import {TierPicker} from '../components/TierPicker';
import {useLocale} from '../i18n/LocaleContext';
import {useConversation} from '../state/ConversationContext';
import {PadiemTheme, radius, spacing, useTheme} from '../ui/theme';
import {VoiceMode} from '../voice/voiceContract';
import {useVoice} from '../voice/useVoice';

const VOICE_MODES: VoiceMode[] = ['M1', 'M2', 'M3', 'M4'];

/**
 * The shared conversation frame.
 *
 * Chat and Claw use this one screen. The product mode only decides which
 * existing server lane the answer is requested from; the layout, the
 * composer, the tier picker and the history are literally the same.
 */
export function ChatScreen(): React.JSX.Element {
  const theme = useTheme();
  const {strings} = useLocale();
  const {
    mode,
    setMode,
    messages,
    conversationId,
    tier,
    allowedTiers,
    adminAvailable,
    tierError,
    selectTier,
    streaming,
    sending,
    error,
    clearError,
    send,
    cancel,
    reset,
    openConversation,
    deviceId,
    setDeviceId,
  } = useConversation();

  const [input, setInput] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [voiceMode, setVoiceMode] = useState<VoiceMode>('M1');
  const listRef = useRef<FlatList<ChatMessage>>(null);
  const attachmentRef = useRef<PickedAttachment | null>(null);

  const handleVoiceFinal = useCallback(
    (text: string) => {
      if (voiceMode === 'M1') {
        // M1: dictate, then the user sends it themselves.
        setInput(current => (current ? `${current} ${text}` : text));
        return;
      }
      // M2/M3/M4: the dictated utterance is the turn.
      void send(text);
    },
    [send, voiceMode],
  );

  const voice = useVoice({
    mode: voiceMode,
    product: mode,
    onFinal: handleVoiceFinal,
  });

  useEffect(() => {
    if (messages.length > 0) {
      listRef.current?.scrollToEnd({animated: true});
    }
  }, [messages.length]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text) {
      return;
    }
    setInput('');
    void send(text);
  }, [input, send]);

  const handleAttach = useCallback((attachment: PickedAttachment) => {
    attachmentRef.current = attachment;
  }, []);

  const handleMic = useCallback(() => {
    if (voice.phase === 'listening') {
      void voice.stop();
      return;
    }
    void voice.start();
  }, [voice]);

  const voiceHint = useMemo(() => {
    if (voice.phase === 'listening') {
      return voice.interim
        ? `${strings.voiceListening} ${voice.interim}`
        : strings.voiceListening;
    }
    if (voice.phase === 'transcribing') {
      return strings.voiceThinking;
    }
    if (voice.phase === 'speaking') {
      return strings.voiceSpeaking;
    }
    if (voice.error) {
      return voice.error;
    }
    return null;
  }, [strings, voice.error, voice.interim, voice.phase]);

  const modeLabels = useMemo(
    () => ({
      chat: strings.chatTab,
      claw: strings.clawTab,
    }),
    [strings.chatTab, strings.clawTab],
  );

  return (
    <KeyboardAvoidingView
      style={[styles.root, {backgroundColor: theme.background}]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 0 : 24}>
      <View style={[styles.header, {backgroundColor: theme.surface, borderBottomColor: theme.border}]}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={strings.recentConversations}
          onPress={() => setSidebarOpen(true)}
          hitSlop={8}
          style={styles.menuButton}>
          <Text style={[styles.menu, {color: theme.text}]}>☰</Text>
        </Pressable>

        <View style={[styles.segment, {backgroundColor: theme.surfaceRaised}]}>
          {(['chat', 'claw'] as const).map(item => {
            const active = mode === item;
            return (
              <Pressable
                key={item}
                accessibilityRole="button"
                onPress={() => setMode(item)}
                style={[
                  styles.segmentItem,
                  active ? {backgroundColor: theme.accentSoft} : null,
                ]}>
                <Text
                  style={[
                    styles.segmentText,
                    {color: active ? theme.accent : theme.textMuted},
                  ]}>
                  {item === 'chat' ? modeLabels.chat : modeLabels.claw}
                </Text>
              </Pressable>
            );
          })}
        </View>

        <TierPicker
          theme={theme}
          tier={tier}
          allowedTiers={allowedTiers}
          adminAvailable={adminAvailable}
          disabled={streaming}
          onSelect={next => {
            void selectTier(next);
          }}
          label={strings.modelLabel}
        />

        <Pressable
          accessibilityRole="button"
          accessibilityLabel={strings.newConversation}
          onPress={() => {
            reset();
            setInput('');
          }}
          hitSlop={8}>
          <Text style={[styles.newChat, {color: theme.accent}]}>＋</Text>
        </Pressable>
      </View>

      {mode === 'claw' ? (
        <ClawStatusBar
          theme={theme}
          conversationId={conversationId}
          deviceId={deviceId}
          onSelectDevice={setDeviceId}
          labels={{
            connected: strings.clawConnected,
            disconnected: strings.clawDisconnected,
            connect: strings.clawConnect,
            refresh: strings.clawRefresh,
            device: strings.clawDevice,
            noDevice: strings.clawNoDevice,
            runs: strings.clawRuns,
            noRuns: strings.clawNoRuns,
            approve: strings.clawApprove,
            reject: strings.clawReject,
          }}
        />
      ) : null}

      {tierError ? (
        <Text style={[styles.bannerText, {color: theme.danger, backgroundColor: theme.surface}]}>
          {tierError}
        </Text>
      ) : null}
      {error ? (
        <Pressable
          onPress={clearError}
          style={[styles.banner, {backgroundColor: theme.surface}]}>
          <Text style={[styles.bannerText, {color: theme.danger}]}>{error}</Text>
        </Pressable>
      ) : null}

      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(item, index) => `${index}-${item.role}`}
        style={styles.list}
        contentContainerStyle={styles.listContent}
        onScrollBeginDrag={() => voice.phase === 'listening' && void voice.stop()}
        renderItem={({item, index}) => (
          <MessageBubble
            message={item}
            theme={theme}
            streaming={
              streaming &&
              index === messages.length - 1 &&
              item.role === 'assistant'
            }
          />
        )}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={[styles.emptyText, {color: theme.textMuted}]}>
              {mode === 'chat' ? strings.appName : strings.clawTab}
            </Text>
          </View>
        }
      />

      <View style={[styles.voiceBar, {backgroundColor: theme.surface}]}>
        {VOICE_MODES.map(item => {
          const active = item === voiceMode;
          const label =
            item === 'M1'
              ? strings.voiceM1
              : item === 'M2'
                ? strings.voiceM2
                : item === 'M3'
                  ? strings.voiceM3
                  : strings.voiceM4;
          return (
            <Pressable
              key={item}
              accessibilityRole="button"
              onPress={() => setVoiceMode(item)}
              style={[
                styles.voiceChip,
                {
                  backgroundColor: active ? theme.accentSoft : theme.surfaceRaised,
                  borderColor: active ? theme.accent : theme.border,
                },
              ]}>
              <Text
                style={[
                  styles.voiceChipText,
                  {color: active ? theme.accent : theme.textMuted},
                ]}>
                {item}
              </Text>
            </Pressable>
          );
        })}
        <Text style={[styles.voiceModeLabel, {color: theme.textMuted}]} numberOfLines={1}>
          {voiceMode === 'M1'
            ? strings.voiceM1
            : voiceMode === 'M2'
              ? strings.voiceM2
              : voiceMode === 'M3'
                ? strings.voiceM3
                : strings.voiceM4}
        </Text>
      </View>

      <Composer
        theme={theme}
        value={input}
        onChangeText={setInput}
        onSend={handleSend}
        onStop={cancel}
        onAttach={handleAttach}
        streaming={streaming}
        sending={sending}
        placeholder={strings.messageInputPlaceholder}
        sendLabel={strings.send}
        stopLabel={strings.stop}
        attachLabel={strings.attach}
        micLabel={strings.mic}
        onMicPress={voice.available ? handleMic : undefined}
        micActive={voice.phase === 'listening'}
        voiceHint={voiceHint}
      />

      <Sidebar
        theme={theme}
        visible={sidebarOpen}
        activeConversationId={conversationId}
        onClose={() => setSidebarOpen(false)}
        onOpen={id => {
          void openConversation(id);
        }}
        onNewConversation={() => {
          reset();
          setInput('');
        }}
        labels={{
          title: strings.appName,
          newConversation: strings.newConversation,
          recent: strings.recentConversations,
          empty: strings.noConversations,
          search: strings.searchConversations,
          close: strings.close,
        }}
      />
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1},
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  menuButton: {marginRight: spacing.sm},
  menu: {fontSize: 18},
  segment: {
    flexDirection: 'row',
    borderRadius: radius.pill,
    padding: 3,
    marginRight: spacing.sm,
  },
  segmentItem: {
    paddingHorizontal: spacing.md,
    paddingVertical: 5,
    borderRadius: radius.pill,
  },
  segmentText: {fontSize: 13, fontWeight: '700'},
  newChat: {fontSize: 20, marginLeft: spacing.sm},
  banner: {paddingHorizontal: spacing.md, paddingVertical: spacing.sm},
  bannerText: {fontSize: 12},
  list: {flex: 1},
  listContent: {paddingVertical: spacing.lg},
  empty: {alignItems: 'center', paddingTop: spacing.xxl},
  emptyText: {fontSize: 13, letterSpacing: 2},
  voiceBar: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  voiceChip: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    marginRight: spacing.xs,
  },
  voiceChipText: {fontSize: 11, fontWeight: '700'},
  voiceModeLabel: {flex: 1, fontSize: 11, marginLeft: spacing.sm},
});
