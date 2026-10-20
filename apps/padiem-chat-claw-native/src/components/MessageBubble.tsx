import React from 'react';
import {StyleSheet, Text, View} from 'react-native';

import {ChatMessage} from '../api/types';
import {PadiemTheme} from '../ui/theme';

interface Props {
  message: ChatMessage;
  theme: PadiemTheme;
  streaming?: boolean;
}

export function MessageBubble({message, theme, streaming}: Props): React.JSX.Element {
  const isUser = message.role === 'user';
  const empty = message.content.trim().length === 0;

  return (
    <View style={[styles.row, isUser ? styles.rowUser : styles.rowAssistant]}>
      <View
        style={[
          styles.bubble,
          {
            backgroundColor: isUser ? theme.userBubble : theme.assistantBubble,
            borderColor: theme.border,
          },
        ]}>
        {!isUser && (
          <Text style={[styles.author, {color: theme.textMuted}]}>
            {streaming ? 'PADIEM' : 'PADIEM'}
          </Text>
        )}
        <Text
          style={[
            styles.body,
            {color: theme.text},
            isUser ? styles.bodyUser : null,
          ]}
          selectable>
          {empty && streaming ? '…' : message.content}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {paddingHorizontal: 12, marginBottom: 10},
  rowUser: {alignItems: 'flex-end'},
  rowAssistant: {alignItems: 'flex-start'},
  bubble: {
    maxWidth: '88%',
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  author: {fontSize: 11, marginBottom: 4, letterSpacing: 0.4},
  body: {fontSize: 15, lineHeight: 22},
  bodyUser: {fontWeight: '500'},
});
