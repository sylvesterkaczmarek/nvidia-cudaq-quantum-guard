from cudaq_guard.doctor import collect_doctor
from cudaq_guard.runtime import CudaQRuntime


class FakeTarget:
    name = "qpp-cpu"
    simulator = "qpp"
    platform = "default"
    description = "CPU"

    def num_qpus(self):
        return 1

    def is_remote(self):
        return False


class FakeCudaQ:
    __version__ = "0.fake"

    def get_targets(self):
        return [FakeTarget()]

    def num_available_gpus(self):
        return 2


def test_doctor_reports_targets_with_fake_runtime() -> None:
    report = collect_doctor(CudaQRuntime(FakeCudaQ()))
    assert report["cudaq_installed"] is True
    assert report["targets"][0]["name"] == "qpp-cpu"
    assert report["targets"][0]["is_remote"] is False
    assert report["cudaq_gpu_count"] == 2
