import React, {useCallback, useEffect, useState} from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import {useNavigation} from '@react-navigation/native';

import {padiemApi} from '../api/padiem';
import {ConversationSummary} from '../api/types';
import {useAuth} from '../auth/AuthContext';
import {useLocale} from '../i18n/LocaleContext';
import {useConversation} from '../state/ConversationContext';
import {PadiemTheme, radius, spacing, useTheme} from '../ui/theme';

function titleOf(conversation: ConversationSummary): string {
  const title = typeof conversation.title === 'string' ? conversation.title.trim() : '';
  if (title) {
    return title;
  }
  const preview = typeof conversation.preview === 'string' ? conversation.preview.trim() : '';
  if (preview) {
    return preview.length > 60 ? `${preview.slice(0, 60)}…` : preview;
  }
  return conversation.id;
}

function updatedLabel(conversation: ConversationSummary): string {
  const value = conversation.updated_at ?? conversation.created_at;
  if (typeof value !== 'string' || !value) {
    return '';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

/**
 * Saved conversation history.
 *
 * The list is the account's own server-side history. Opening one restores it
 * into the shared conversation frame; deleting one asks the server to remove
 * it. The app keeps no shadow copy.
 */
export function HistoryScreen(): React.JSX.Element {
  const theme = useTheme();
  const {strings} = useLocale();
  const navigation = useNavigation();
  const {signedIn} = useAuth();
  const {openConversation, conversationId} = useConversation();

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (search: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = search.trim()
        ? await padiemApi.searchConversations(search.trim())
        : await padiemApi.conversations();
      setConversations(Array.isArray(response.conversations) ? response.conversations : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : strings.unknownError);
      setConversations([]);
    } finally {
      setLoading(false);
    }
  }, [strings.unknownError]);

  useEffect(() => {
    if (signedIn) {
      void load(query);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signedIn]);

  const handleOpen = useCallback(
    async (id: string) => {
      await openConversation(id);
      navigation.navigate('Chat' as never);
    },
    [navigation, openConversation],
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await padiemApi.deleteConversation(id);
      } catch {
        // The refreshed list below shows the server's own state.
      }
      await load(query);
    },
    [load, query],
  );

  return (
    <View style={[styles.root, {backgroundColor: theme.background}]}>
      <View style={[styles.header, {borderBottomColor: theme.border}]}>
        <Text style={[styles.title, {color: theme.text}]}>{strings.historyTab}</Text>
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
            onSubmitEditing={() => void load(query)}
            placeholder={strings.searchConversations}
            placeholderTextColor={theme.textMuted}
            returnKeyType="search"
          />
          <Pressable accessibilityRole="button" onPress={() => void load(query)}>
            <Text style={[styles.searchAction, {color: theme.accent}]}>↵</Text>
          </Pressable>
        </View>
      </View>

      {error ? (
        <Text style={[styles.error, {color: theme.danger}]}>{error}</Text>
      ) : null}

      {loading ? (
        <ActivityIndicator style={styles.loader} color={theme.textMuted} />
      ) : (
        <FlatList
          data={conversations}
          keyExtractor={item => item.id}
          contentContainerStyle={styles.listContent}
          renderItem={({item}) => {
            const active = item.id === conversationId;
            return (
              <View
                style={[
                  styles.item,
                  {
                    backgroundColor: theme.surface,
                    borderColor: active ? theme.accent : theme.border,
                  },
                ]}>
                <Pressable
                  accessibilityRole="button"
                  onPress={() => void handleOpen(item.id)}
                  style={styles.itemBody}>
                  <Text
                    style={[
                      styles.itemTitle,
                      {color: active ? theme.accent : theme.text},
                    ]}
                    numberOfLines={2}>
                    {titleOf(item)}
                  </Text>
                  <Text style={[styles.itemMeta, {color: theme.textMuted}]} numberOfLines={1}>
                    {updatedLabel(item)}
                  </Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={strings.deleteConversation}
                  onPress={() => void handleDelete(item.id)}
                  hitSlop={8}
                  style={styles.deleteButton}>
                  <Text style={[styles.deleteText, {color: theme.danger}]}>🗑</Text>
                </Pressable>
              </View>
            );
          }}
          ListEmptyComponent={
            <Text style={[styles.empty, {color: theme.textMuted}]}>
              {strings.noConversations}
            </Text>
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1},
  header: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  title: {fontSize: 20, fontWeight: '700', marginBottom: spacing.md},
  searchRow: {flexDirection: 'row', alignItems: 'center'},
  searchInput: {
    flex: 1,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    fontSize: 14,
  },
  searchAction: {fontSize: 16, marginLeft: spacing.md},
  listContent: {padding: spacing.md},
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  itemBody: {flex: 1},
  itemTitle: {fontSize: 15},
  itemMeta: {fontSize: 11, marginTop: 4},
  deleteButton: {marginLeft: spacing.md},
  deleteText: {fontSize: 15},
  empty: {textAlign: 'center', marginTop: spacing.xxl, fontSize: 13},
  error: {fontSize: 12, paddingHorizontal: spacing.md, paddingTop: spacing.sm},
  loader: {marginTop: spacing.xxl},
});
