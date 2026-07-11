// Auth state machine: login -> (optional TOTP step) -> authenticated.
// Mirrors the web dashboard's reducer (frontend/lib/auth-reducer.ts).

import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../models/auth.dart';

enum AuthStatus { anonymous, submitting, mfaRequired, authenticated }

class AuthState extends ChangeNotifier {
  AuthState(this._api) {
    _api.onAuthFailure = _onAuthFailure;
  }

  final ApiClient _api;

  AuthStatus _status = AuthStatus.anonymous;
  String? _mfaPendingToken;
  String? _error;
  UserOut? _user;

  AuthStatus get status => _status;
  String? get error => _error;
  UserOut? get user => _user;
  bool get isAdmin => _user?.isAdmin ?? false;

  Future<void> login(String email, String password) async {
    _status = AuthStatus.submitting;
    _error = null;
    notifyListeners();
    try {
      final json = await _api.post(
        '/api/auth/login',
        body: {'email': email, 'password': password},
      ) as Map<String, dynamic>;
      final result = LoginResult.fromJson(json);
      if (result.mfaRequired && result.mfaPendingToken != null) {
        _mfaPendingToken = result.mfaPendingToken;
        _status = AuthStatus.mfaRequired;
      } else {
        await _completeLogin(result);
      }
    } on ApiException catch (err) {
      _error = err.statusCode == 0 ? 'Gateway unreachable' : err.message;
      _status = AuthStatus.anonymous;
    }
    notifyListeners();
  }

  Future<void> submitMfa(String code) async {
    final pending = _mfaPendingToken;
    if (pending == null) return;
    _status = AuthStatus.submitting;
    _error = null;
    notifyListeners();
    try {
      final json = await _api.post(
        '/api/auth/login/mfa',
        body: {'mfa_pending_token': pending, 'code': code},
      ) as Map<String, dynamic>;
      await _completeLogin(LoginResult.fromJson(json));
    } on ApiException catch (err) {
      // Stay on the TOTP step: the pending token is still valid.
      _error = err.statusCode == 0 ? 'Gateway unreachable' : err.message;
      _status = AuthStatus.mfaRequired;
    }
    notifyListeners();
  }

  void cancelMfa() {
    _mfaPendingToken = null;
    _error = null;
    _status = AuthStatus.anonymous;
    notifyListeners();
  }

  Future<void> logout() async {
    final refresh = _api.refreshToken;
    if (refresh != null) {
      try {
        // Best-effort server-side revocation.
        await _api.post('/api/auth/logout', body: {'refresh_token': refresh});
      } on ApiException {
        // Gateway down: still log out locally.
      }
    }
    _reset();
    notifyListeners();
  }

  Future<void> _completeLogin(LoginResult result) async {
    if (result.accessToken == null) {
      _error = 'Login failed: no token returned';
      _status = AuthStatus.anonymous;
      return;
    }
    _api.setTokens(access: result.accessToken, refresh: result.refreshToken);
    final me = await _api.get('/api/auth/me') as Map<String, dynamic>;
    _user = UserOut.fromJson(me);
    _mfaPendingToken = null;
    _status = AuthStatus.authenticated;
  }

  void _onAuthFailure() {
    if (_status == AuthStatus.authenticated) {
      _reset();
      notifyListeners();
    }
  }

  void _reset() {
    _api.clearTokens();
    _user = null;
    _mfaPendingToken = null;
    _error = null;
    _status = AuthStatus.anonymous;
  }
}
