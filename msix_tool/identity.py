from __future__ import annotations

import ctypes
import hashlib
import os
import re
import zipfile
from ctypes import wintypes
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from .models import PackageIdentity


class IdentityError(RuntimeError):
    pass


MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_PACKAGE_ENTRIES = 20_000
MAX_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024

ARCHITECTURES = {
    "x86": 0,
    "arm": 5,
    "x64": 9,
    "neutral": 11,
    "arm64": 12,
    "x86a64": 14,
}


class PACKAGE_ID(ctypes.Structure):
    _fields_ = [
        ("reserved", wintypes.UINT),
        ("processorArchitecture", wintypes.UINT),
        ("version", ctypes.c_uint64),
        ("name", wintypes.LPWSTR),
        ("publisher", wintypes.LPWSTR),
        ("resourceId", wintypes.LPWSTR),
        ("publisherId", wintypes.LPWSTR),
    ]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(parent: ET.Element, local_name: str) -> ET.Element | None:
    return next((node for node in list(parent) if _local_name(node.tag) == local_name), None)


def _descendant(parent: ET.Element, local_name: str) -> ET.Element | None:
    return next((node for node in parent.iter() if _local_name(node.tag) == local_name), None)


def _validated_archive(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > MAX_PACKAGE_ENTRIES:
        raise IdentityError("MSIX contains too many entries")
    if sum(item.file_size for item in entries) > MAX_UNCOMPRESSED_BYTES:
        raise IdentityError("MSIX uncompressed size exceeds the safety limit")
    names: dict[str, zipfile.ZipInfo] = {}
    for item in entries:
        normalized = item.filename.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or "\x00" in normalized:
            raise IdentityError(f"Unsafe MSIX entry: {item.filename}")
        key = normalized.casefold()
        if key in names:
            raise IdentityError(f"Duplicate MSIX entry name: {item.filename}")
        names[key] = item
    return names


def parse_msix(path: Path) -> PackageIdentity:
    path = path.resolve()
    if not path.is_file() or path.suffix.casefold() != ".msix":
        raise IdentityError(f"MSIX file was not found: {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            names = _validated_archive(archive)
            manifest_info = names.get("appxmanifest.xml")
            if manifest_info is None:
                raise IdentityError("AppxManifest.xml is missing")
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise IdentityError("AppxManifest.xml exceeds the safety limit")
            manifest = archive.read(manifest_info)
            if archive.testzip() is not None:
                raise IdentityError("MSIX CRC validation failed")
    except zipfile.BadZipFile as exc:
        raise IdentityError("MSIX is not a valid ZIP container") from exc
    try:
        root = ET.fromstring(manifest)
    except ET.ParseError as exc:
        raise IdentityError(f"AppxManifest.xml is invalid: {exc}") from exc
    if _local_name(root.tag) != "Package":
        raise IdentityError("Manifest root is not Package")
    identity_node = _child(root, "Identity")
    properties = _child(root, "Properties")
    application = _descendant(root, "Application")
    if identity_node is None:
        raise IdentityError("Manifest Identity is missing")
    identity = PackageIdentity(
        name=identity_node.get("Name", "").strip(),
        publisher=identity_node.get("Publisher", "").strip(),
        version=identity_node.get("Version", "").strip(),
        architecture=identity_node.get("ProcessorArchitecture", "").strip(),
        resource_id=identity_node.get("ResourceId", "").strip(),
        application_id=application.get("Id", "").strip() if application is not None else "",
        executable=application.get("Executable", "").strip() if application is not None else "",
    )
    if properties is not None:
        display = _child(properties, "DisplayName")
        publisher_display = _child(properties, "PublisherDisplayName")
        identity.display_name = (display.text or "").strip() if display is not None else ""
        identity.publisher_display_name = (
            (publisher_display.text or "").strip() if publisher_display is not None else ""
        )
    if not identity.name or not identity.publisher or not identity.version:
        raise IdentityError("Manifest Identity Name, Publisher, or Version is empty")
    derived = derive_windows_identity(identity)
    identity.publisher_id = derived.publisher_id
    identity.package_family_name = derived.package_family_name
    identity.package_sid = derived.package_sid
    identity.package_full_name = derived.package_full_name
    return identity


def _version_raw(version: str) -> int:
    if not re.fullmatch(r"[0-9]{1,5}(?:[.][0-9]{1,5}){3}", version):
        raise IdentityError(f"Invalid package version: {version}")
    major, minor, build, revision = (int(item) for item in version.split("."))
    if max(major, minor, build, revision) > 65535:
        raise IdentityError(f"Invalid package version: {version}")
    return (major << 48) | (minor << 32) | (build << 16) | revision


def _format_from_id(function_name: str, package_id: PACKAGE_ID) -> str:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = getattr(kernel32, function_name)
    function.argtypes = [ctypes.POINTER(PACKAGE_ID), ctypes.POINTER(wintypes.UINT), wintypes.LPWSTR]
    function.restype = wintypes.LONG
    length = wintypes.UINT(0)
    result = function(ctypes.byref(package_id), ctypes.byref(length), None)
    if result != 122 or length.value == 0:  # ERROR_INSUFFICIENT_BUFFER
        raise IdentityError(f"{function_name} sizing failed with Win32 error {result}")
    buffer = ctypes.create_unicode_buffer(length.value)
    result = function(ctypes.byref(package_id), ctypes.byref(length), buffer)
    if result != 0:
        raise IdentityError(f"{function_name} failed with Win32 error {result}")
    return buffer.value


def _package_sid(package_family_name: str) -> str:
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    derive = userenv.DeriveAppContainerSidFromAppContainerName
    derive.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    derive.restype = ctypes.c_long
    convert = advapi32.ConvertSidToStringSidW
    convert.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    convert.restype = wintypes.BOOL
    free_sid = advapi32.FreeSid
    free_sid.argtypes = [ctypes.c_void_p]
    free_sid.restype = ctypes.c_void_p
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    sid = ctypes.c_void_p()
    string_sid = ctypes.c_void_p()
    result = derive(package_family_name, ctypes.byref(sid))
    if result < 0:
        raise IdentityError(f"DeriveAppContainerSidFromAppContainerName failed: 0x{result & 0xFFFFFFFF:08X}")
    try:
        if not convert(sid, ctypes.byref(string_sid)):
            raise IdentityError(f"ConvertSidToStringSidW failed: {ctypes.get_last_error()}")
        return ctypes.wstring_at(string_sid)
    finally:
        if string_sid.value:
            local_free(string_sid)
        if sid.value:
            free_sid(sid)


def derive_windows_identity(source: PackageIdentity) -> PackageIdentity:
    if os.name != "nt":
        raise IdentityError("PFN and Package SID derivation requires Windows official APIs")
    architecture = ARCHITECTURES.get(source.architecture.casefold())
    if architecture is None:
        raise IdentityError(f"Unsupported package architecture: {source.architecture}")
    package_id = PACKAGE_ID(
        reserved=0,
        processorArchitecture=architecture,
        version=_version_raw(source.version),
        name=source.name,
        publisher=source.publisher,
        resourceId=source.resource_id or None,
        publisherId=None,
    )
    family_name = _format_from_id("PackageFamilyNameFromId", package_id)
    full_name = _format_from_id("PackageFullNameFromId", package_id)
    if "_" not in family_name:
        raise IdentityError("Windows returned an invalid package family name")
    publisher_id = family_name.rsplit("_", 1)[1]
    return PackageIdentity(
        publisher_id=publisher_id,
        package_family_name=family_name,
        package_sid=_package_sid(family_name),
        package_full_name=full_name,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()
