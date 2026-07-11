// TradingPlatform mobile app — Fase 13.
// Presentation only: display + configuration. The app consumes exclusively
// the gateway service (docs/ARCHITECTURE.md); no trading logic lives here.

import 'package:flutter/material.dart';

import 'api/api_client.dart';
import 'screens/home_shell.dart';
import 'screens/login_screen.dart';
import 'state/alerts_state.dart';
import 'state/app_scope.dart';
import 'state/auth_state.dart';
import 'state/dashboard_state.dart';
import 'state/settings_state.dart';
import 'state/strategies_state.dart';

/// Override at build time: flutter run --dart-define=GATEWAY_URL=http://host:8000
/// Default targets the host machine from the Android emulator.
const String kDefaultGatewayUrl = String.fromEnvironment(
  'GATEWAY_URL',
  defaultValue: 'http://10.0.2.2:8000',
);

void main() {
  final api = ApiClient(baseUrl: kDefaultGatewayUrl);
  runApp(TradingPlatformApp(api: api));
}

class TradingPlatformApp extends StatefulWidget {
  const TradingPlatformApp({super.key, required this.api});

  final ApiClient api;

  @override
  State<TradingPlatformApp> createState() => _TradingPlatformAppState();
}

class _TradingPlatformAppState extends State<TradingPlatformApp> {
  late final AuthState _auth;
  late final SettingsState _settings;
  late final DashboardState _dashboard;
  late final StrategiesState _strategies;
  late final AlertsState _alerts;

  @override
  void initState() {
    super.initState();
    _auth = AuthState(widget.api);
    _settings = SettingsState(widget.api);
    _dashboard = DashboardState(widget.api);
    _strategies = StrategiesState(widget.api);
    _alerts = AlertsState(widget.api);
  }

  @override
  Widget build(BuildContext context) {
    return AppScope(
      api: widget.api,
      auth: _auth,
      settings: _settings,
      dashboard: _dashboard,
      strategies: _strategies,
      alerts: _alerts,
      child: MaterialApp(
        title: 'TradingPlatform',
        debugShowCheckedModeBanner: false,
        theme: _buildTheme(),
        home: ListenableBuilder(
          listenable: _auth,
          builder: (context, _) => _auth.status == AuthStatus.authenticated
              ? const HomeShell()
              : const LoginScreen(),
        ),
      ),
    );
  }

  /// Dark trading-terminal theme: neutral dark background (#0b0e14, no pure
  /// black), light text, indigo accent — mirrors the web dashboard palette.
  ThemeData _buildTheme() {
    const background = Color(0xFF0B0E14);
    const panel = Color(0xFF12161F);
    final scheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF4F46E5),
      brightness: Brightness.dark,
      surface: panel,
    );
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: background,
      appBarTheme: const AppBarTheme(
        backgroundColor: panel,
        elevation: 0,
      ),
      cardTheme: CardTheme(
        color: panel,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(8),
          side: const BorderSide(color: Color(0xFF232936)),
        ),
      ),
      navigationBarTheme: const NavigationBarThemeData(
        backgroundColor: panel,
      ),
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
      ),
    );
  }
}
