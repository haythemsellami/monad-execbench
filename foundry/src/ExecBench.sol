// SPDX-License-Identifier: GPL-3.0-only
pragma solidity >=0.8.20;

interface ExecBenchVm {
    function writeJson(string calldata json, string calldata path) external;
}

/// @notice Builds call manifests consumed by monad-execbench capture.
/// @dev Intended for Forge scripts and tests. The helper only writes local files
///      through the standard Foundry cheatcode address; it is not deployable code.
library ExecBench {
    string internal constant CALLS_SCHEMA = "monad-execbench/calls-v1";

    ExecBenchVm private constant _VM =
        ExecBenchVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    error CapacityExceeded(uint256 capacity);
    error EmptyCaseName();
    error EmptyMetadataKey();
    error InvalidMetadataKey(string key);
    error DuplicateMetadataKey(string key);

    struct Label {
        string key;
        string value;
    }

    struct Counter {
        string key;
        uint256 value;
    }

    struct AccessListEntry {
        address account;
        bytes32[] storageKeys;
    }

    struct Options {
        bool hasGas;
        uint256 gas;
        bool hasGasPrice;
        uint256 gasPrice;
        AccessListEntry[] accessList;
        Label[] labels;
        Counter[] counters;
    }

    struct Call {
        string name;
        address caller;
        address target;
        bytes input;
        uint256 value;
        Options options;
    }

    struct Manifest {
        Call[] calls;
        uint256 length;
    }

    function create(uint256 capacity) internal pure returns (Manifest memory manifest) {
        manifest.calls = new Call[](capacity);
    }

    function addCall(
        Manifest memory manifest,
        string memory name,
        address caller,
        address target,
        bytes memory input,
        uint256 value
    ) internal pure {
        Options memory options;
        addCall(manifest, name, caller, target, input, value, options);
    }

    function addCall(
        Manifest memory manifest,
        string memory name,
        address caller,
        address target,
        bytes memory input,
        uint256 value,
        Options memory options
    ) internal pure {
        if (manifest.length == manifest.calls.length) {
            revert CapacityExceeded(manifest.calls.length);
        }
        if (bytes(name).length == 0) revert EmptyCaseName();
        _validateMetadata(options.labels, options.counters);
        manifest.calls[manifest.length] = Call({
            name: name, caller: caller, target: target, input: input, value: value, options: options
        });
        ++manifest.length;
    }

    function write(Manifest memory manifest, string memory path) internal {
        _VM.writeJson(toJson(manifest), path);
    }

    function toJson(Manifest memory manifest) internal pure returns (string memory) {
        bytes memory result = abi.encodePacked('{"cases":[');
        for (uint256 i; i < manifest.length; ++i) {
            if (i != 0) result = abi.encodePacked(result, ",");
            result = abi.encodePacked(result, _callJson(manifest.calls[i]));
        }
        return string(abi.encodePacked(result, '],"schema":"', CALLS_SCHEMA, '"}'));
    }

    function _callJson(Call memory call_) private pure returns (bytes memory) {
        Options memory options = call_.options;
        bytes memory result = abi.encodePacked(
            '{"from":',
            _jsonString(_addressString(call_.caller)),
            ',"input":',
            _jsonString(_bytesString(call_.input)),
            ',"name":',
            _jsonString(call_.name),
            ',"to":',
            _jsonString(_addressString(call_.target)),
            ',"value":"',
            _uintString(call_.value),
            '"'
        );
        if (options.hasGas) {
            result = abi.encodePacked(result, ',"gas":"', _uintString(options.gas), '"');
        }
        if (options.hasGasPrice) {
            result = abi.encodePacked(result, ',"gasPrice":"', _uintString(options.gasPrice), '"');
        }
        if (options.accessList.length != 0) {
            result = abi.encodePacked(result, ',"accessList":', _accessListJson(options.accessList));
        }
        if (options.labels.length != 0 || options.counters.length != 0) {
            result = abi.encodePacked(
                result, ',"metadata":', _metadataJson(options.labels, options.counters)
            );
        }
        return abi.encodePacked(result, "}");
    }

    function _metadataJson(Label[] memory labels, Counter[] memory counters)
        private
        pure
        returns (bytes memory)
    {
        bytes memory result = "{";
        if (labels.length != 0) {
            result = abi.encodePacked(result, '"labels":{');
            for (uint256 i; i < labels.length; ++i) {
                if (i != 0) result = abi.encodePacked(result, ",");
                result = abi.encodePacked(
                    result, _jsonString(labels[i].key), ":", _jsonString(labels[i].value)
                );
            }
            result = abi.encodePacked(result, "}");
        }
        if (counters.length != 0) {
            if (labels.length != 0) result = abi.encodePacked(result, ",");
            result = abi.encodePacked(result, '"counters":{');
            for (uint256 i; i < counters.length; ++i) {
                if (i != 0) result = abi.encodePacked(result, ",");
                result = abi.encodePacked(
                    result, _jsonString(counters[i].key), ':"', _uintString(counters[i].value), '"'
                );
            }
            result = abi.encodePacked(result, "}");
        }
        return abi.encodePacked(result, "}");
    }

    function _accessListJson(AccessListEntry[] memory accessList)
        private
        pure
        returns (bytes memory)
    {
        bytes memory result = "[";
        for (uint256 i; i < accessList.length; ++i) {
            if (i != 0) result = abi.encodePacked(result, ",");
            result = abi.encodePacked(
                result,
                '{"address":',
                _jsonString(_addressString(accessList[i].account)),
                ',"storageKeys":['
            );
            for (uint256 j; j < accessList[i].storageKeys.length; ++j) {
                if (j != 0) result = abi.encodePacked(result, ",");
                result = abi.encodePacked(
                    result, _jsonString(_bytes32String(accessList[i].storageKeys[j]))
                );
            }
            result = abi.encodePacked(result, "]}");
        }
        return abi.encodePacked(result, "]");
    }

    function _validateMetadata(Label[] memory labels, Counter[] memory counters) private pure {
        for (uint256 i; i < labels.length; ++i) {
            _validateMetadataKey(labels[i].key);
            for (uint256 j; j < i; ++j) {
                if (keccak256(bytes(labels[i].key)) == keccak256(bytes(labels[j].key))) {
                    revert DuplicateMetadataKey(labels[i].key);
                }
            }
        }
        for (uint256 i; i < counters.length; ++i) {
            _validateMetadataKey(counters[i].key);
            bytes32 keyHash = keccak256(bytes(counters[i].key));
            if (
                keyHash == keccak256("execution_gas") || keyHash == keccak256("return_data_bytes")
                    || keyHash == keccak256("log_count")
            ) revert InvalidMetadataKey(counters[i].key);
            for (uint256 j; j < i; ++j) {
                if (keyHash == keccak256(bytes(counters[j].key))) {
                    revert DuplicateMetadataKey(counters[i].key);
                }
            }
        }
    }

    function _validateMetadataKey(string memory key) private pure {
        bytes memory value = bytes(key);
        if (value.length == 0) revert EmptyMetadataKey();
        if (value.length > 64 || !_isNameStart(value[0])) revert InvalidMetadataKey(key);
        for (uint256 i = 1; i < value.length; ++i) {
            bytes1 character = value[i];
            if (
                !_isNameStart(character) && (character < "0" || character > "9") && character != "."
                    && character != "-"
            ) {
                revert InvalidMetadataKey(key);
            }
        }
    }

    function _isNameStart(bytes1 character) private pure returns (bool) {
        return character == "_" || (character >= "a" && character <= "z")
            || (character >= "A" && character <= "Z");
    }

    function _jsonString(string memory value) private pure returns (bytes memory) {
        bytes memory input = bytes(value);
        bytes memory output = '"';
        bytes16 hexDigits = "0123456789abcdef";
        for (uint256 i; i < input.length; ++i) {
            bytes1 character = input[i];
            if (character == '"' || character == "\\") {
                output = abi.encodePacked(output, "\\", character);
            } else if (character == 0x08) {
                output = abi.encodePacked(output, "\\b");
            } else if (character == 0x09) {
                output = abi.encodePacked(output, "\\t");
            } else if (character == 0x0a) {
                output = abi.encodePacked(output, "\\n");
            } else if (character == 0x0c) {
                output = abi.encodePacked(output, "\\f");
            } else if (character == 0x0d) {
                output = abi.encodePacked(output, "\\r");
            } else if (uint8(character) < 0x20) {
                output = abi.encodePacked(
                    output,
                    "\\u00",
                    hexDigits[uint8(character) >> 4],
                    hexDigits[uint8(character) & 0x0f]
                );
            } else {
                output = abi.encodePacked(output, character);
            }
        }
        return abi.encodePacked(output, '"');
    }

    function _addressString(address value) private pure returns (string memory) {
        return _fixedHexString(bytes32(uint256(uint160(value))), 20);
    }

    function _bytes32String(bytes32 value) private pure returns (string memory) {
        return _fixedHexString(value, 32);
    }

    function _fixedHexString(bytes32 value, uint256 length) private pure returns (string memory) {
        bytes16 hexDigits = "0123456789abcdef";
        bytes memory result = new bytes(2 + length * 2);
        result[0] = "0";
        result[1] = "x";
        uint256 offset = 32 - length;
        for (uint256 i; i < length; ++i) {
            uint8 character = uint8(value[offset + i]);
            result[2 + i * 2] = hexDigits[character >> 4];
            result[3 + i * 2] = hexDigits[character & 0x0f];
        }
        return string(result);
    }

    function _bytesString(bytes memory value) private pure returns (string memory) {
        bytes16 hexDigits = "0123456789abcdef";
        bytes memory result = new bytes(2 + value.length * 2);
        result[0] = "0";
        result[1] = "x";
        for (uint256 i; i < value.length; ++i) {
            uint8 character = uint8(value[i]);
            result[2 + i * 2] = hexDigits[character >> 4];
            result[3 + i * 2] = hexDigits[character & 0x0f];
        }
        return string(result);
    }

    function _uintString(uint256 value) private pure returns (string memory) {
        if (value == 0) return "0";
        uint256 digits;
        uint256 remaining = value;
        while (remaining != 0) {
            ++digits;
            remaining /= 10;
        }
        bytes memory result = new bytes(digits);
        while (value != 0) {
            result[--digits] = bytes1(uint8(48 + value % 10));
            value /= 10;
        }
        return string(result);
    }
}
