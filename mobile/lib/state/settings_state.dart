// App settings: gateway URL, account id and the Demo/Real indicator.
// Presentation state only — the paper/live gate is enforced server-side by
// the execution-engine (admin-only override).

import 'package:flutter/foundation.dart';

import '../api/api_client.dart';

class SettingsState extends ChangeNotifier {
  SettingsState(this._api);

  final ApiClient _api;

  String _accountId = 'default';
  bool _liveMode = false; // false = DEMO/paper (default), true = REAL/live

  String get gatewayUrl => _api.baseUrl;
  String get accountId => _accountId;
  bool get liveMode => _liveMode;

  void setGatewayUrl(String url) {
    final trimmed = url.trim();
    if (trimmed.isEmpty || trimmed == _api.baseUrl) return;
    _api.baseUrl = trimmed;
    notifyListeners();
  }

  void setAccountId(String id) {
    final trimmed = id.trim();
    _accountId = trimmed.isEmpty ? 'default' : trimmed;
    notifyListeners();
  }

  void setLiveMode(bool value) {
    if (_liveMode == value) return;
    _liveMode = value;
    notifyListeners();
  }
}
