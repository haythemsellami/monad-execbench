// SPDX-License-Identifier: GPL-3.0-only
pragma solidity >=0.8.20;

import { ExecBench } from "src/ExecBench.sol";

interface IPrepareIntegrationVm {
    function addr(uint256 privateKey) external pure returns (address);
    function envString(string calldata name) external view returns (string memory);
    function envUint(string calldata name) external view returns (uint256);
    function startBroadcast(uint256 privateKey) external;
    function stopBroadcast() external;
}

contract IntegrationProbe {
    mapping(uint256 key => uint256 value) private values;

    error ProbeRevert(uint256 value);

    event Observed(uint256 indexed key, uint256 value);

    constructor() {
        values[1] = 42;
    }

    function read(uint256 key) external view returns (uint256) {
        return values[key];
    }

    function write(uint256 key, uint256 value) external {
        values[key] = value;
    }

    function readAndRevert(uint256 key) external view {
        revert ProbeRevert(values[key]);
    }

    function revertRoot() external pure {
        revert ProbeRevert(0xdeadbeef);
    }

    function emitLog(uint256 key) external {
        emit Observed(key, values[key]);
    }
}

contract IntegrationRoot {
    IntegrationProbe private immutable PROBE;
    uint256 private marker;

    event BetweenChildren(uint256 value);

    constructor(IntegrationProbe probe_) {
        PROBE = probe_;
        marker = 7;
    }

    function catchNestedRevert(uint256 key) external view returns (uint256) {
        try PROBE.readAndRevert(key) {
            return 0;
        } catch {
            return marker;
        }
    }

    function emitBetweenChildren() external {
        PROBE.emitLog(1);
        emit BetweenChildren(marker);
        PROBE.emitLog(2);
    }
}

/// @dev Deploys the integration probes and writes their call manifest.
contract PrepareIntegration {
    using ExecBench for ExecBench.Manifest;

    IPrepareIntegrationVm private constant _VM =
        IPrepareIntegrationVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function run() external {
        uint256 privateKey = _VM.envUint("EXECBENCH_PRIVATE_KEY");
        address caller = _VM.addr(privateKey);

        _VM.startBroadcast(privateKey);
        IntegrationProbe probe = new IntegrationProbe();
        IntegrationRoot root = new IntegrationRoot(probe);
        _VM.stopBroadcast();

        ExecBench.Manifest memory manifest = ExecBench.create(7);
        manifest.addCall(
            "probe/nested-revert-read",
            caller,
            address(root),
            abi.encodeCall(IntegrationRoot.catchNestedRevert, (1)),
            0
        );

        ExecBench.Options memory readOptions;
        readOptions.labels = new ExecBench.Label[](1);
        readOptions.labels[0] = ExecBench.Label({ key: "operation", value: "storage-read" });
        readOptions.counters = new ExecBench.Counter[](1);
        readOptions.counters[0] = ExecBench.Counter({ key: "input_value", value: 1 });
        manifest.addCall(
            "probe/storage-read",
            caller,
            address(probe),
            abi.encodeCall(IntegrationProbe.read, (1)),
            0,
            readOptions
        );
        manifest.addCall(
            "probe/storage-write",
            caller,
            address(probe),
            abi.encodeCall(IntegrationProbe.write, (2, 99)),
            0
        );

        manifest.addCall(
            "probe/root-revert",
            caller,
            address(probe),
            abi.encodeCall(IntegrationProbe.revertRoot, ()),
            0
        );
        manifest.addCall(
            "probe/log", caller, address(probe), abi.encodeCall(IntegrationProbe.emitLog, (1)), 0
        );
        manifest.addCall(
            "probe/nested-log-order",
            caller,
            address(root),
            abi.encodeCall(IntegrationRoot.emitBetweenChildren, ()),
            0
        );

        ExecBench.Options memory accessListOptions;
        accessListOptions.accessList = new ExecBench.AccessListEntry[](1);
        bytes32[] memory storageKeys = new bytes32[](1);
        storageKeys[0] = keccak256(abi.encode(uint256(1), uint256(0)));
        accessListOptions.accessList[0] =
            ExecBench.AccessListEntry({ account: address(probe), storageKeys: storageKeys });
        manifest.addCall(
            "probe/access-list",
            caller,
            address(probe),
            abi.encodeCall(IntegrationProbe.read, (1)),
            0,
            accessListOptions
        );

        manifest.write(_VM.envString("EXECBENCH_CALLS_PATH"));
    }
}
