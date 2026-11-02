// The system registry: a name -> the two backends of a rule system.

#include "core/sim/kernels.h"

#include <map>
#include <stdexcept>

namespace pysim {
namespace {

struct Entry {
    SystemSpec spec;
    BackendFactory host;
    BackendFactory cuda;
};

std::map<std::string, Entry>& registry() {
    static std::map<std::string, Entry> reg;
    return reg;
}

}  // namespace

void register_system(const SystemSpec& spec, BackendFactory host_factory,
                     BackendFactory cuda_factory) {
    Entry entry;
    entry.spec = spec;
    entry.host = std::move(host_factory);
    entry.cuda = std::move(cuda_factory);
    registry()[spec.name] = std::move(entry);
}

std::vector<SystemSpec> registered_systems() {
    std::vector<SystemSpec> out;
    out.reserve(registry().size());
    for (const auto& kv : registry()) out.push_back(kv.second.spec);
    return out;
}

std::unique_ptr<Backend> make_backend(const std::string& name, const ParamMap& params,
                                       uint32_t num_envs, uint32_t rows, bool cuda) {
    auto it = registry().find(name);
    if (it == registry().end()) {
        throw std::runtime_error("pysim: no such system: " + name);
    }
    const BackendFactory& factory = cuda ? it->second.cuda : it->second.host;
    if (!factory) {
        throw std::runtime_error("pysim: the system has no " +
                                 std::string(cuda ? "CUDA" : "host") + " backend: " + name);
    }
    return factory(params, num_envs, rows);
}

}  // namespace pysim
