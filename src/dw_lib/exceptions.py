# --- dw_lib.loader ---
class ConnectionNotFoundException(Exception):
    pass


class StreamNotFoundException(Exception):
    pass


class TableCopyException(Exception):
    pass


class ConfigFileNotFoundException(Exception):
    pass


# --- dw_lib.peerdb ---
class EmptyConfigException(Exception):
    pass


class PeerExistsException(Exception):
    pass


class PeerNotFoundException(Exception):
    pass


class MirrorExistsException(Exception):
    pass


class MirrorNotFoundException(Exception):
    pass


class MirrorTimeoutException(Exception):
    pass


class TableNotFoundException(Exception):
    pass


class UnsupportedAdapterException(Exception):
    pass


class PeerDBAPIException(Exception):
    pass


class GetDynamicSettingsException(PeerDBAPIException):
    pass


class SetDynamicSettingsException(PeerDBAPIException):
    pass


class GetPeerInfoException(PeerDBAPIException):
    pass


class GetPeerTypeException(PeerDBAPIException):
    pass


class CreatePeerException(PeerDBAPIException):
    pass


class DropPeerException(PeerDBAPIException):
    pass


class ListPeersException(PeerDBAPIException):
    pass


class GetMirrorStatusException(PeerDBAPIException):
    pass


class CreateMirrorException(PeerDBAPIException):
    pass


class DropMirrorException(PeerDBAPIException):
    pass


class ResyncMirrorException(PeerDBAPIException):
    pass


class PauseMirrorException(PeerDBAPIException):
    pass


class ResumeMirrorException(PeerDBAPIException):
    pass


class ListMirrorsException(PeerDBAPIException):
    pass


# --- dw_lib.database.adapters ---
class DatabaseExistsException(Exception):
    pass


class DatabaseNotFoundException(Exception):
    pass


class TableExistsException(Exception):
    pass


class UserExistsException(Exception):
    pass


class UserNotFoundException(Exception):
    pass


class PublicationExistsException(Exception):
    pass


class PublicationNotFoundException(Exception):
    pass


# --- dw_lib.dbt ---
class DbtManifestNotFoundException(Exception):
    pass


class UnsupportedCommandException(Exception):
    pass


class UnsupportedRunStatusException(Exception):
    pass


# --- dw_lib.utils.sqlmodel_utils ---
class TableExpressionNotFoundException(Exception):
    pass
