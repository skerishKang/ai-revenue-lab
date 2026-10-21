/**
 * PADIEM Chat & Claw - native Android client.
 *
 * One React Native application that speaks the existing PADIEM server
 * contracts: the signed session, the account-scoped AI tier, the Chat
 * streaming lane, the Claw general composer and the shared voice route.
 * The app adds no server, no authentication rule and no model rule of its
 * own.
 *
 * @format
 */

import React from 'react';
import {ActivityIndicator, StatusBar, StyleSheet, View} from 'react-native';
import {NavigationContainer, DarkTheme, DefaultTheme} from '@react-navigation/native';
import {createBottomTabNavigator} from '@react-navigation/bottom-tabs';
import {SafeAreaProvider} from 'react-native-safe-area-context';

import {AuthProvider, useAuth} from './src/auth/AuthContext';
import {LocaleProvider, useLocale} from './src/i18n/LocaleContext';
import {ChatScreen} from './src/screens/ChatScreen';
import {HistoryScreen} from './src/screens/HistoryScreen';
import {LoginScreen} from './src/screens/LoginScreen';
import {SettingsScreen} from './src/screens/SettingsScreen';
import {ConversationProvider} from './src/state/ConversationContext';
import {useTheme} from './src/ui/theme';

const Tab = createBottomTabNavigator();

function Splash(): React.JSX.Element {
  return (
    <View style={styles.splash}>
      <ActivityIndicator size="large" color="#6ea8fe" />
    </View>
  );
}

function MainTabs(): React.JSX.Element {
  const theme = useTheme();
  const {strings} = useLocale();

  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: theme.accent,
        tabBarInactiveTintColor: theme.textMuted,
        tabBarStyle: {
          backgroundColor: theme.surface,
          borderTopColor: theme.border,
        },
      }}>
      <Tab.Screen
        name="Chat"
        component={ChatScreen}
        options={{tabBarLabel: strings.chatTab}}
      />
      <Tab.Screen
        name="History"
        component={HistoryScreen}
        options={{tabBarLabel: strings.historyTab}}
      />
      <Tab.Screen
        name="Settings"
        component={SettingsScreen}
        options={{tabBarLabel: strings.settingsTab}}
      />
    </Tab.Navigator>
  );
}

function Root(): React.JSX.Element {
  const theme = useTheme();
  const {ready, signedIn} = useAuth();

  const base = theme.dark ? DarkTheme : DefaultTheme;
  const navigationTheme = {
    ...base,
    colors: {
      ...base.colors,
      background: theme.background,
      card: theme.surface,
      text: theme.text,
      border: theme.border,
      primary: theme.accent,
    },
  };

  if (!ready) {
    return <Splash />;
  }

  if (!signedIn) {
    return <LoginScreen />;
  }

  return (
    <NavigationContainer theme={navigationTheme}>
      <MainTabs />
    </NavigationContainer>
  );
}

function App(): React.JSX.Element {
  const theme = useTheme();

  return (
    <SafeAreaProvider>
      <StatusBar
        barStyle={theme.dark ? 'light-content' : 'dark-content'}
        backgroundColor={theme.background}
      />
      <LocaleProvider>
        <AuthProvider>
          <ConversationProvider>
            <Root />
          </ConversationProvider>
        </AuthProvider>
      </LocaleProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  splash: {flex: 1, alignItems: 'center', justifyContent: 'center'},
});

export default App;
