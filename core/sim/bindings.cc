// The pybind11 module: one module, every rule system.
//
// The interface the design names (docs/design/batched-sim.md §1.2):
//
//   batch = pysim.make_batch("beacons", num_envs=4096, rows=200, device="cuda")
//   batch.apply_actions(actions)      # actions: int32 (num_envs,)
//   batch.legal_action_mask()          # bool (num_envs, A)
//   batch.obs()                        # float32 (num_envs, C, H, W)
//   batch.reward()                     # float32 (num_envs,)
//   batch.reset(seed_table=None)       # reset from the seed table
//
// The backend reuses its buffers, so **every array this module returns is a
// fresh copy** -- the rule the Stratego port carried over verbatim.
//
// The arrays are numpy, not torch: torch is not installed on this box, and
// the shape contract is what the callers need. `core/sim/__init__.py` wraps
// them so a caller that does have torch gets `torch.from_numpy` for free.

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

#include "core/sim/kernels.h"
#include "core/sim/systems/register.h"

namespace py = pybind11;

namespace pysim {

// The array flags: C-contiguous, and cast the caller's array if it is not.
// (A `using` alias cannot hold an expression, so this is a constant.)
constexpr int ArrayFlags = py::array::c_style | py::array::forcecast;

namespace {

class BatchHandle {
public:
    BatchHandle(std::unique_ptr<Backend> backend, uint32_t num_envs, uint32_t rows)
        : backend_(std::move(backend)), num_envs_(num_envs), rows_(rows) {
        const SystemSpec& spec = backend_->spec();
        obs_len_ = (size_t)spec.obs_channels * spec.obs_width * spec.obs_height;
    }

    // Reset from a seed table: one seed per world.
    void reset(py::array_t<uint64_t, ArrayFlags> seeds) {
        if ((uint32_t)seeds.size() != num_envs_) {
            throw std::runtime_error("pysim: the seed table must have one seed per world");
        }
        std::vector<uint64_t> host((size_t)num_envs_);
        std::memcpy(host.data(), seeds.data(), host.size() * sizeof(uint64_t));
        backend_->reset(host.data());
    }

    void apply_actions(py::array_t<int32_t, ArrayFlags> actions) {
        if ((uint32_t)actions.size() != num_envs_) {
            throw std::runtime_error("pysim: one action per world");
        }
        std::vector<int32_t> host((size_t)num_envs_);
        std::memcpy(host.data(), actions.data(), host.size() * sizeof(int32_t));
        backend_->apply_actions(host.data());
    }

    py::array_t<bool> legal_action_mask() {
        const uint32_t a = backend_->spec().num_actions;
        py::array_t<bool> out({(py::ssize_t)num_envs_, (py::ssize_t)a});
        backend_->legal_action_mask(out.mutable_data());
        return out;
    }

    py::array_t<float> obs() {
        const SystemSpec& spec = backend_->spec();
        py::array_t<float> out({(py::ssize_t)num_envs_, (py::ssize_t)spec.obs_channels,
                                (py::ssize_t)spec.obs_height, (py::ssize_t)spec.obs_width});
        backend_->obs(out.mutable_data());
        return out;
    }

    py::array_t<float> reward() {
        py::array_t<float> out((py::ssize_t)num_envs_);
        py::array_t<int32_t> terminated((py::ssize_t)num_envs_);
        backend_->reward_and_terminated(out.mutable_data(), terminated.mutable_data());
        return out;
    }

    py::array_t<int32_t> terminated() {
        py::array_t<float> reward((py::ssize_t)num_envs_);
        py::array_t<int32_t> out((py::ssize_t)num_envs_);
        backend_->reward_and_terminated(reward.mutable_data(), out.mutable_data());
        return out;
    }

    py::array_t<uint8_t> state_bytes() {
        const uint32_t n = backend_->spec().state_serial_bytes;
        py::array_t<uint8_t> out({(py::ssize_t)num_envs_, (py::ssize_t)n});
        backend_->serialize_states(out.mutable_data());
        return out;
    }

    py::array_t<uint8_t> world_bytes() {
        const uint32_t n = backend_->spec().world_serial_bytes;
        py::array_t<uint8_t> out({(py::ssize_t)num_envs_, (py::ssize_t)n});
        backend_->serialize_worlds(out.mutable_data());
        return out;
    }

    const SystemSpec& spec() const { return backend_->spec(); }
    uint32_t row() const { return backend_->row(); }

private:
    std::unique_ptr<Backend> backend_;
    uint32_t num_envs_ = 0;
    uint32_t rows_ = 1;
    size_t obs_len_ = 0;
};

py::dict spec_to_dict(const SystemSpec& spec) {
    py::dict d;
    d["name"] = spec.name;
    d["num_actions"] = spec.num_actions;
    d["obs_channels"] = spec.obs_channels;
    d["obs_width"] = spec.obs_width;
    d["obs_height"] = spec.obs_height;
    d["obs_history"] = spec.obs_history;
    d["state_bytes"] = spec.state_bytes;
    d["state_serial_bytes"] = spec.state_serial_bytes;
    d["world_bytes"] = spec.world_bytes;
    d["world_serial_bytes"] = spec.world_serial_bytes;
    return d;
}

}  // namespace
}  // namespace pysim

PYBIND11_MODULE(_pysim, m) {
    m.doc() = "pysim: the batched simulator's Python binding.";

    // Every rule system registers itself here.
    pysim::systems::register_all_systems();

    m.def("systems", []() {
        py::list out;
        for (const pysim::SystemSpec& spec : pysim::registered_systems()) {
            out.append(pysim::spec_to_dict(spec));
        }
        return out;
    });

    m.def("make_batch",
          [](const std::string& system, uint32_t num_envs, uint32_t rows,
             const std::string& device, uint64_t seed, const pysim::ParamMap& params) {
              if (num_envs == 0) throw std::runtime_error("pysim: num_envs must be positive");
              if (rows == 0) rows = 1;
              const bool cuda = (device == "cuda" || device == "gpu");
              auto backend = pysim::make_backend(system, params, num_envs, rows, cuda);
              auto handle = std::unique_ptr<pysim::BatchHandle>(
                  new pysim::BatchHandle(std::move(backend), num_envs, rows));
              // The default seed table: one stream per world, so the worlds
              // are different but the batch is reproducible.
              std::vector<uint64_t> seeds(num_envs);
              for (uint32_t i = 0; i < num_envs; ++i) seeds[i] = seed + (uint64_t)i;
              handle->reset(py::array_t<uint64_t, pysim::ArrayFlags>(
                  (size_t)num_envs, seeds.data()));
              return handle;
          },
          py::arg("system"), py::arg("num_envs") = 1024, py::arg("rows") = 1,
          py::arg("device") = "cuda", py::arg("seed") = 0,
          py::arg("params") = pysim::ParamMap(), "Make a batch of worlds.");

    py::class_<pysim::BatchHandle>(m, "Batch")
        .def("reset", &pysim::BatchHandle::reset, py::arg("seeds"),
             "Reset every world from its seed.")
        .def("apply_actions", &pysim::BatchHandle::apply_actions, py::arg("actions"),
             "Advance every world by one ply.")
        .def("legal_action_mask", &pysim::BatchHandle::legal_action_mask,
             "The legal actions of the acting player, (num_envs, A).")
        .def("obs", &pysim::BatchHandle::obs, "The observation planes, (num_envs, C, H, W).")
        .def("reward", &pysim::BatchHandle::reward, "The reward of the last step, (num_envs,).")
        .def("terminated", &pysim::BatchHandle::terminated,
             "The terminated flag of the last step, (num_envs,).")
        .def("state_bytes", &pysim::BatchHandle::state_bytes,
             "The canonical byte encoding of every state.")
        .def("world_bytes", &pysim::BatchHandle::world_bytes,
             "The canonical byte encoding of every world.")
        .def_property_readonly("row", &pysim::BatchHandle::row,
                               "The row the live state is in.")
        .def_property_readonly("num_envs",
                               [](const pysim::BatchHandle& h) { return h.spec().num_actions; },
                               "The action count of the system.")
        .def_property_readonly("num_actions",
                               [](const pysim::BatchHandle& h) { return h.spec().num_actions; },
                               "The action count of the system.")
        .def_property_readonly("spec",
                               [](const pysim::BatchHandle& h) {
                                   return pysim::spec_to_dict(h.spec());
                               },
                               "The system's spec.");
}
