// DTOs for /api/auth/* responses (services/auth-service/app/schemas.py).

double _asDouble(Object? value) => value is num ? value.toDouble() : 0.0;

class LoginResult {
  const LoginResult({
    this.accessToken,
    this.refreshToken,
    this.mfaRequired = false,
    this.mfaPendingToken,
  });

  factory LoginResult.fromJson(Map<String, dynamic> json) => LoginResult(
        accessToken: json['access_token'] as String?,
        refreshToken: json['refresh_token'] as String?,
        mfaRequired: json['mfa_required'] as bool? ?? false,
        mfaPendingToken: json['mfa_pending_token'] as String?,
      );

  final String? accessToken;
  final String? refreshToken;
  final bool mfaRequired;
  final String? mfaPendingToken;
}

class UserOut {
  const UserOut({
    required this.id,
    required this.email,
    required this.roles,
    this.mfaEnabled = false,
  });

  factory UserOut.fromJson(Map<String, dynamic> json) => UserOut(
        id: json['id'] as String? ?? '',
        email: json['email'] as String? ?? '',
        roles: (json['roles'] as List<dynamic>? ?? const [])
            .map((r) => r.toString())
            .toList(growable: false),
        mfaEnabled: json['mfa_enabled'] as bool? ?? false,
      );

  final String id;
  final String email;
  final List<String> roles;
  final bool mfaEnabled;

  bool get isAdmin => roles.contains('admin');
}

// Shared numeric helper for the other model files.
double asDouble(Object? value) => _asDouble(value);
