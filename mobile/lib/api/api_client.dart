// Gateway HTTP client. The mobile app talks ONLY to the gateway
// (docs/ARCHITECTURE.md: clients never call an internal service directly).
//
// - Injects `Authorization: Bearer <access>` on every request.
// - On 401 (outside /api/auth/*): refreshes once via POST /api/auth/refresh
//   (single-flight) and retries the original request exactly once.
// - On refresh failure: clears tokens and fires [onAuthFailure] so the auth
//   state can send the user back to the login screen.
//
// Tokens are held in memory only. PRODUCTION TODO: persist the refresh token
// in platform secure storage (flutter_secure_storage / Keychain / Keystore),
// never in plain SharedPreferences.

import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  ApiException(this.statusCode, this.message);

  /// 0 means the gateway itself was unreachable (network error).
  final int statusCode;
  final String message;

  @override
  String toString() => 'ApiException($statusCode): $message';
}

class ApiClient {
  ApiClient({required String baseUrl, http.Client? httpClient})
      : _baseUrl = _normalize(baseUrl),
        _http = httpClient ?? http.Client();

  String _baseUrl;
  final http.Client _http;

  String? _accessToken;
  String? _refreshToken;
  Future<bool>? _refreshInFlight;

  /// Called when a refresh attempt fails: the session is over.
  void Function()? onAuthFailure;

  String get baseUrl => _baseUrl;
  set baseUrl(String value) => _baseUrl = _normalize(value);

  String? get refreshToken => _refreshToken;
  bool get hasSession => _accessToken != null;

  static String _normalize(String url) =>
      url.endsWith('/') ? url.substring(0, url.length - 1) : url;

  void setTokens({String? access, String? refresh}) {
    if (access != null) _accessToken = access;
    if (refresh != null) _refreshToken = refresh;
  }

  void clearTokens() {
    _accessToken = null;
    _refreshToken = null;
  }

  Uri _uri(String path, Map<String, String>? query) {
    final uri = Uri.parse('$_baseUrl$path');
    if (query == null || query.isEmpty) return uri;
    return uri.replace(queryParameters: {...uri.queryParameters, ...query});
  }

  Future<dynamic> get(String path, {Map<String, String>? query}) =>
      _send('GET', path, query: query);

  Future<dynamic> post(String path, {Object? body, Map<String, String>? query}) =>
      _send('POST', path, body: body, query: query);

  Future<dynamic> put(String path, {Object? body}) => _send('PUT', path, body: body);

  Future<dynamic> patch(String path, {Object? body}) => _send('PATCH', path, body: body);

  Future<dynamic> _send(
    String method,
    String path, {
    Object? body,
    Map<String, String>? query,
    bool retried = false,
  }) async {
    http.Response response;
    try {
      final request = http.Request(method, _uri(path, query));
      if (_accessToken != null) {
        request.headers['Authorization'] = 'Bearer $_accessToken';
      }
      if (body != null) {
        request.headers['Content-Type'] = 'application/json';
        request.body = jsonEncode(body);
      }
      response = await http.Response.fromStream(await _http.send(request));
    } catch (err) {
      throw ApiException(0, 'Gateway unreachable');
    }

    // 401 on a protected route -> refresh once -> retry once. Auth endpoints
    // are exempt: a 401 there means bad credentials, not an expired token.
    if (response.statusCode == 401 && !path.startsWith('/api/auth/') && !retried) {
      final refreshed = await _refresh();
      if (refreshed) {
        return _send(method, path, body: body, query: query, retried: true);
      }
      clearTokens();
      onAuthFailure?.call();
    }

    if (response.statusCode >= 400) {
      throw ApiException(response.statusCode, _detailOf(response));
    }
    if (response.body.isEmpty) return null;
    return jsonDecode(utf8.decode(response.bodyBytes));
  }

  Future<bool> _refresh() {
    // Single-flight: concurrent 401s share one refresh round-trip.
    return _refreshInFlight ??= _doRefresh().whenComplete(() {
      _refreshInFlight = null;
    });
  }

  Future<bool> _doRefresh() async {
    final token = _refreshToken;
    if (token == null) return false;
    try {
      final response = await _http.post(
        _uri('/api/auth/refresh', null),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'refresh_token': token}),
      );
      if (response.statusCode >= 400) return false;
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      if (data is! Map<String, dynamic>) return false;
      final access = data['access_token'] as String?;
      if (access == null) return false;
      _accessToken = access;
      final refresh = data['refresh_token'] as String?;
      if (refresh != null) _refreshToken = refresh;
      return true;
    } catch (_) {
      return false;
    }
  }

  static String _detailOf(http.Response response) {
    try {
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      if (data is Map<String, dynamic> && data['detail'] != null) {
        final detail = data['detail'];
        return detail is String ? detail : jsonEncode(detail);
      }
    } catch (_) {
      // fall through
    }
    return 'Request failed (${response.statusCode})';
  }
}
