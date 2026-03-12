class ASVPError(Exception):
    pass


class ASVPCryptoUnavailable(ASVPError):
    pass


class ASVPVerificationFailed(ASVPError):
    pass

