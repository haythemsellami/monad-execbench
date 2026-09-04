// SPDX-License-Identifier: GPL-3.0-only
pragma solidity ^0.8.26;

import { ExecBench } from "src/ExecBench.sol";

interface TestVm {
    function readFile(string calldata path) external view returns (string memory);
    function removeFile(string calldata path) external;
    function parseJsonAddress(string calldata json, string calldata key)
        external
        pure
        returns (address);
    function parseJsonBytes(string calldata json, string calldata key)
        external
        pure
        returns (bytes memory);
    function parseJsonString(string calldata json, string calldata key)
        external
        pure
        returns (string memory);
    function parseJsonUint(string calldata json, string calldata key)
        external
        pure
        returns (uint256);
}

contract ExecBenchTest {
    using ExecBench for ExecBench.Manifest;

    TestVm private constant _VM = TestVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function test_rendersSimpleCall() public pure {
        ExecBench.Manifest memory manifest = ExecBench.create(1);
        manifest.addCall(
            "example/simple",
            address(0x1111111111111111111111111111111111111111),
            address(0x2222222222222222222222222222222222222222),
            hex"1234",
            42
        );

        string memory json = manifest.toJson();
        _assertEq(_VM.parseJsonString(json, ".schema"), "monad-execbench/calls-v1");
        _assertEq(_VM.parseJsonString(json, ".cases[0].name"), "example/simple");
        _assertEq(
            _VM.parseJsonAddress(json, ".cases[0].from"),
            address(0x1111111111111111111111111111111111111111)
        );
        _assertEq(_VM.parseJsonBytes(json, ".cases[0].input"), hex"1234");
        _assertEq(_VM.parseJsonUint(json, ".cases[0].value"), 42);
    }

    function test_rendersOptionsAndMetadata() public pure {
        ExecBench.Manifest memory manifest = ExecBench.create(1);
        ExecBench.Options memory options;
        options.hasGas = true;
        options.gas = 5_000_000;
        options.hasGasPrice = true;
        options.gasPrice = 7;
        options.labels = new ExecBench.Label[](2);
        options.labels[0] = ExecBench.Label({ key: "implementation", value: "example-a" });
        options.labels[1] = ExecBench.Label({ key: "note", value: "quote\"and\\slash\n" });
        options.counters = new ExecBench.Counter[](1);
        options.counters[0] = ExecBench.Counter({ key: "amount_in", value: type(uint256).max });
        options.accessList = new ExecBench.AccessListEntry[](1);
        bytes32[] memory storageKeys = new bytes32[](1);
        storageKeys[0] = bytes32(uint256(3));
        options.accessList[0] = ExecBench.AccessListEntry({
            account: address(0x3333333333333333333333333333333333333333), storageKeys: storageKeys
        });

        manifest.addCall(
            "example/options",
            address(0x1111111111111111111111111111111111111111),
            address(0x2222222222222222222222222222222222222222),
            hex"",
            0,
            options
        );

        string memory json = manifest.toJson();
        _assertEq(_VM.parseJsonUint(json, ".cases[0].gas"), 5_000_000);
        _assertEq(_VM.parseJsonUint(json, ".cases[0].gasPrice"), 7);
        _assertEq(
            _VM.parseJsonAddress(json, ".cases[0].accessList[0].address"),
            address(0x3333333333333333333333333333333333333333)
        );
        _assertEq(
            _VM.parseJsonString(json, ".cases[0].metadata.labels.note"), "quote\"and\\slash\n"
        );
        _assertEq(
            _VM.parseJsonString(json, ".cases[0].metadata.counters.amount_in"),
            "115792089237316195423570985008687907853269984665640564039457584007913129639935"
        );
    }

    function test_writesManifest() public {
        ExecBench.Manifest memory manifest = ExecBench.create(1);
        manifest.addCall("example/write", address(1), address(2), hex"", 0);
        string memory path = "out/execbench-call-manifest.json";
        manifest.write(path);
        string memory json = _VM.readFile(path);
        _assertEq(_VM.parseJsonString(json, ".cases[0].name"), "example/write");
        _VM.removeFile(path);
    }

    function test_rejectsCapacityOverflow() public view {
        ExecBench.Manifest memory manifest = ExecBench.create(0);
        try this.addSimple(manifest) {
            revert("expected revert");
        } catch (bytes memory reason) {
            _assertEq(_selector(reason), ExecBench.CapacityExceeded.selector);
        }
    }

    function test_rejectsReservedCounter() public view {
        ExecBench.Manifest memory manifest = ExecBench.create(1);
        ExecBench.Options memory options;
        options.counters = new ExecBench.Counter[](1);
        options.counters[0] = ExecBench.Counter({ key: "execution_gas", value: 1 });
        try this.addWithOptions(manifest, options) {
            revert("expected revert");
        } catch (bytes memory reason) {
            _assertEq(_selector(reason), ExecBench.InvalidMetadataKey.selector);
        }
    }

    function addSimple(ExecBench.Manifest memory manifest) external pure {
        manifest.addCall("x", address(1), address(2), hex"", 0);
    }

    function addWithOptions(ExecBench.Manifest memory manifest, ExecBench.Options memory options)
        external
        pure
    {
        manifest.addCall("x", address(1), address(2), hex"", 0, options);
    }

    function _selector(bytes memory reason) private pure returns (bytes4 result) {
        assembly ("memory-safe") {
            result := mload(add(reason, 0x20))
        }
    }

    function _assertEq(string memory actual, string memory expected) private pure {
        require(keccak256(bytes(actual)) == keccak256(bytes(expected)), "string mismatch");
    }

    function _assertEq(address actual, address expected) private pure {
        require(actual == expected, "address mismatch");
    }

    function _assertEq(uint256 actual, uint256 expected) private pure {
        require(actual == expected, "uint mismatch");
    }

    function _assertEq(bytes memory actual, bytes memory expected) private pure {
        require(keccak256(actual) == keccak256(expected), "bytes mismatch");
    }

    function _assertEq(bytes4 actual, bytes4 expected) private pure {
        require(actual == expected, "selector mismatch");
    }
}
