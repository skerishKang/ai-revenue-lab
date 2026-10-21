import React, {useCallback, useEffect, useState} from 'react';
import {
  ActivityIndicator,
  FlatList,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import {padiemApi} from '../api/padiem';
import {ConversationSummary} from '../api/types';
import {PadiemTheme, radius, spacing} from '../ui/theme';

interface Props {
  theme: PadiemTheme;
  visible: boolean;
  activeConversationId: string | null;
  onClose: () => void;
  onOpen: (conversationId: string) => void;
  onNewConversation: () => void;
  labels: {
    title: string;
    newConversation: string;
    recent: string;
    empty: string;
    search: string;
    close: string;
  };
}

function titleOf(conversation: ConversationSummary): string {
  const title = typeof conversation.title === 'string' ? conversation.title.trim() : '';
  if (title) {
    return title;
  }
  const preview = typeof conversation.preview === 'string' ? conversation.preview.trim() : '';
  if (preview) {
    return preview.length > 40 ? `${preview.slice(0, 40)}…` : preview;
  }
  return conversation.id;
}

/**
 * Sidebar with the recent conversations.
 *
 * The list is the account's own server-side history; the app does not keep a
 * second copy of it and does not decide which conversations exist.
 */
export function Sidebar({
  theme,
  visible,
  activeConversationId,
  onClose,
  onOpen,
  onNewConversation,
  labels,
}: Props): React.JSX.Element {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (search: string) => {
    setLoading(true);
    try {
      const response = search.trim()
        ? await padiemApi.searchConversations(search.trim())
        : await padiemApi.conversations();
      setConversations(Array.isArray(response.conversations) ? response.conversations : []);
    } catch {
      setConversations([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (visible) {
      void load(query);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const handleSearch = useCallback(() => {
    void load(query);
  }, [load, query]);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <Pressable style={styles.dismissArea} onPress={onClose} />
        <View
          style={[
            styles.panel,
            {backgroundColor: theme.surface, borderColor: theme.border},
          ]}>
          <View style={styles.header}>
            <Text style={[styles.title, {color: theme.text}]}>{labels.title}</Text>
            <Pressable accessibilityRole="button" onPress={onClose} hitSlop={10}>
              <Text style={[styles.close, {color: theme.textMuted}]}>{labels.close}</Text>
            </Pressable>
          </View>

          <Pressable
            accessibilityRole="button"
            onPress={() => {
              onNewConversation();
              onClose();
            }}
            style={[styles.newButton, {backgroundColor: theme.accent}]}>
            <Text style={styles.newLabel}>{labels.newConversation}</Text>
          </Pressable>

          <View style={styles.searchRow}>
            <TextInput
              style={[
                styles.searchInput,
                {
                  backgroundColor: theme.surfaceRaised,
                  borderColor: theme.border,
                  color: theme.text,
                },
              ]}
              value={query}
              onChangeText={setQuery}
              onSubmitEditing={handleSearch}
              placeholder={labels.search}
              placeholderTextColor={theme.textMuted}
              returnKeyType="search"
            />
            <Pressable accessibilityRole="button" onPress={handleSearch}>
              <Text style={[styles.searchAction, {color: theme.accent}]}>↵</Text>
            </Pressable>
          </View>

          <Text style={[styles.sectionTitle, {color: theme.textMuted}]}>{labels.recent}</Text>

          {loading ? (
            <ActivityIndicator style={styles.loader} color={theme.textMuted} />
          ) : (
            <FlatList
              data={conversations}
              keyExtractor={item => item.id}
              style={styles.list}
              renderItem={({item}) => {
                const active = item.id === activeConversationId;
                return (
                  <Pressable
                    accessibilityRole="button"
                    onPress={() => {
                      onOpen(item.id);
                      onClose();
                    }}
                    style={[
                      styles.item,
                      {
                        backgroundColor: active ? theme.accentSoft : 'transparent',
                        borderBottomColor: theme.border,
                      },
                    ]}>
                    <Text
                      style={[
                        styles.itemText,
                        {color: active ? theme.accent : theme.text},
                      ]}
                      numberOfLines={2}>
                      {titleOf(item)}
                    </Text>
                  </Pressable>
                );
              }}
              ListEmptyComponent={
                <Text style={[styles.empty, {color: theme.textMuted}]}>{labels.empty}</Text>
              }
            />
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {flex: 1, flexDirection: 'row', backgroundColor: 'rgba(0,0,0,0.5)'},
  dismissArea: {flex: 1},
  panel: {
    width: '84%',
    maxWidth: 360,
    borderRightWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xl,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.lg,
  },
  title: {fontSize: 18, fontWeight: '700'},
  close: {fontSize: 13},
  newButton: {
    borderRadius: radius.pill,
    paddingVertical: spacing.md,
    alignItems: 'center',
    marginBottom: spacing.lg,
  },
  newLabel: {color: '#0b1020', fontWeight: '700', fontSize: 14},
  searchRow: {flexDirection: 'row', alignItems: 'center', marginBottom: spacing.lg},
  searchInput: {
    flex: 1,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    fontSize: 14,
  },
  searchAction: {fontSize: 16, marginLeft: spacing.md},
  sectionTitle: {fontSize: 11, marginBottom: spacing.sm, letterSpacing: 0.4},
  list: {flex: 1},
  item: {
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  itemText: {fontSize: 14},
  empty: {fontSize: 13, paddingVertical: spacing.lg},
  loader: {marginTop: spacing.xl},
});
