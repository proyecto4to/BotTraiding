// Dependency scope: exposes the shared ApiClient and the ChangeNotifier
// providers to the widget tree without an external state package.
// Screens rebuild with ListenableBuilder(listenable: AppScope.of(ctx).xyz).

import 'package:flutter/widgets.dart';

import '../api/api_client.dart';
import 'alerts_state.dart';
import 'auth_state.dart';
import 'dashboard_state.dart';
import 'settings_state.dart';
import 'strategies_state.dart';

class AppScope extends InheritedWidget {
  const AppScope({
    super.key,
    required this.api,
    required this.auth,
    required this.settings,
    required this.dashboard,
    required this.strategies,
    required this.alerts,
    required super.child,
  });

  final ApiClient api;
  final AuthState auth;
  final SettingsState settings;
  final DashboardState dashboard;
  final StrategiesState strategies;
  final AlertsState alerts;

  static AppScope of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<AppScope>();
    assert(scope != null, 'AppScope is missing above this widget');
    return scope!;
  }

  @override
  bool updateShouldNotify(AppScope oldWidget) => false;
}
