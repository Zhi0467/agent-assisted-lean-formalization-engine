"""
Perceptron mistake-bound experiments for DSC 190/291 HW1 Part C.

Implements:
  - Data generator with known margin γ and bound R
  - Online Perceptron algorithm
  - Four experiments verifying the R²/γ² mistake bound
"""

import warnings
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

warnings.filterwarnings("ignore", category=RuntimeWarning)

SEED = 42
OUTPUT_DIR = Path(__file__).parent / "plots"
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Core implementations
# ---------------------------------------------------------------------------

def generate_data(d: int, n: int, gamma: float, R: float,
                  rng: np.random.Generator) -> tuple:
    """
    Generate n points in R^d with ‖x‖ ≤ R, linearly separable by a random
    hyperplane with margin ≥ γ.

    Strategy: decompose each x into its component along the separator u*
    and its orthogonal complement.  Sample the parallel component uniformly
    from [-R, -γ] ∪ [γ, R] so the margin condition holds by construction,
    then fill the orthogonal part randomly within the remaining norm budget.
    """
    assert 0 < gamma <= R

    u_star = rng.standard_normal(d)
    u_star /= np.linalg.norm(u_star)

    # parallel component: uniform on [γ, R] with random sign
    signs = rng.choice([-1, 1], size=n)
    parallel_mag = rng.uniform(gamma, R, size=n)
    parallel = (signs * parallel_mag)[:, None] * u_star[None, :]  # (n, d)

    # orthogonal component: random direction ⊥ u*, with norm ≤ sqrt(R² - a²)
    raw = rng.standard_normal((n, d))
    raw -= (raw @ u_star)[:, None] * u_star[None, :]  # project out u*
    raw_norms = np.linalg.norm(raw, axis=1, keepdims=True)
    raw_norms = np.maximum(raw_norms, 1e-12)
    budget = np.sqrt(np.maximum(R**2 - parallel_mag**2, 0))
    scale = (rng.uniform(0, 1, size=n) * budget)[:, None]
    ortho = raw / raw_norms * scale

    xs = parallel + ortho
    ys = signs  # label = sign of the parallel component

    return xs, ys, u_star


def perceptron(xs: np.ndarray, ys: np.ndarray) -> int:
    """Online Perceptron; returns total number of mistakes."""
    d = xs.shape[1]
    w = np.zeros(d)
    mistakes = 0
    for x, y in zip(xs, ys):
        if y * (w @ x) <= 0:
            w += y * x
            mistakes += 1
    return mistakes


# ---------------------------------------------------------------------------
# Experiment helpers
# ---------------------------------------------------------------------------

def run_trials(d, n, gamma, R, num_trials, seed_base):
    """Return array of mistake counts over independent trials."""
    counts = []
    for t in range(num_trials):
        rng = np.random.default_rng(seed_base + t * 1000)
        xs, ys, _ = generate_data(d, n, gamma, R, rng)
        counts.append(perceptron(xs, ys))
    return np.array(counts)


# ---------------------------------------------------------------------------
# Experiment 1 — M vs 1/γ²
# ---------------------------------------------------------------------------

def experiment_m_vs_inv_gamma_sq():
    print("=== Experiment 1: M vs 1/γ² ===")
    d, n, R = 50, 2000, 1.0
    gammas = np.linspace(0.05, 0.5, 20)
    inv_g2 = 1.0 / gammas**2
    means, stds = [], []

    for g in gammas:
        counts = run_trials(d, n, g, R, num_trials=20, seed_base=SEED)
        means.append(counts.mean())
        stds.append(counts.std())
        print(f"  γ={g:.3f}  1/γ²={1/g**2:>8.1f}  M={counts.mean():.1f} ± {counts.std():.1f}")

    means, stds = np.asarray(means), np.asarray(stds)

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.errorbar(inv_g2, means, yerr=stds, fmt="o-", capsize=3, label="Empirical M")

    coeffs = np.polyfit(inv_g2, means, 1)
    ax.plot(inv_g2, np.polyval(coeffs, inv_g2), "r--",
            label=f"Linear fit: M ≈ {coeffs[0]:.4f}·(1/γ²) + {coeffs[1]:.1f}")
    ax.plot(inv_g2, R**2 * inv_g2, "k:", alpha=0.5, label=f"Bound R²/γ²")

    ax.set_xlabel("1/γ²")
    ax.set_ylabel("Number of mistakes M")
    ax.set_title("Perceptron mistakes vs 1/γ²  (d=50, R=1)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "exp1_m_vs_inv_gamma_sq.png", dpi=150)
    plt.close(fig)
    print(f"  → saved exp1_m_vs_inv_gamma_sq.png\n")


# ---------------------------------------------------------------------------
# Experiment 2 — Tightness of the bound
# ---------------------------------------------------------------------------

def experiment_tightness():
    print("=== Experiment 2: Tightness of R²/γ² ===")
    d, n, R = 50, 2000, 1.0
    gammas = np.linspace(0.05, 0.5, 20)
    means = []

    for g in gammas:
        counts = run_trials(d, n, g, R, num_trials=20, seed_base=SEED + 100)
        means.append(counts.mean())

    means = np.asarray(means)
    bound = R**2 / gammas**2
    ratio = means / bound

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    axes[0].plot(gammas, means, "o-", label="Empirical M")
    axes[0].plot(gammas, bound, "s--", label="Bound R²/γ²")
    axes[0].set_xlabel("γ")
    axes[0].set_ylabel("Mistakes")
    axes[0].set_title("Empirical M vs theoretical bound")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(gammas, ratio, "o-", color="tab:orange")
    axes[1].set_xlabel("γ")
    axes[1].set_ylabel("M / (R²/γ²)")
    axes[1].set_title("Ratio: empirical / worst-case bound")
    axes[1].axhline(1, ls=":", color="gray")
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "exp2_tightness.png", dpi=150)
    plt.close(fig)
    for g, m, r in zip(gammas, means, ratio):
        print(f"  γ={g:.3f}  M={m:.1f}  ratio={r:.4f}")
    print(f"  → saved exp2_tightness.png\n")


# ---------------------------------------------------------------------------
# Experiment 3 — Dimension independence
# ---------------------------------------------------------------------------

def experiment_dimension_independence():
    print("=== Experiment 3: Dimension independence ===")
    dims = [2, 10, 100, 1000]
    n, R = 2000, 1.0
    gammas = np.linspace(0.05, 0.5, 15)

    fig, ax = plt.subplots(figsize=(7, 5))
    for d in dims:
        means = []
        for g in gammas:
            counts = run_trials(d, n, g, R, num_trials=15, seed_base=SEED + 200 + d)
            means.append(counts.mean())
        ax.plot(1 / gammas**2, means, "o-", markersize=4, label=f"d = {d}")
        print(f"  d={d:>5d}: mistakes in [{min(means):.0f}, {max(means):.0f}]")

    ax.plot(1 / gammas**2, R**2 / gammas**2, "k:", alpha=0.4, label="Bound R²/γ²")
    ax.set_xlabel("1/γ²")
    ax.set_ylabel("Number of mistakes M")
    ax.set_title("Dimension independence of Perceptron mistakes")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "exp3_dimension_independence.png", dpi=150)
    plt.close(fig)
    print(f"  → saved exp3_dimension_independence.png\n")


# ---------------------------------------------------------------------------
# Experiment 4 — γ → 0
# ---------------------------------------------------------------------------

def experiment_gamma_to_zero():
    print("=== Experiment 4: γ → 0 ===")
    d, n, R = 50, 5000, 1.0
    gammas = np.logspace(-3, -0.3, 25)
    means, stds = [], []

    for g in gammas:
        counts = run_trials(d, n, g, R, num_trials=10, seed_base=SEED + 300)
        means.append(counts.mean())
        stds.append(counts.std())
        print(f"  γ={g:.5f}  M={counts.mean():.1f} ± {counts.std():.1f}")

    means, stds = np.asarray(means), np.asarray(stds)
    bound = R**2 / gammas**2

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.errorbar(gammas, means, yerr=stds, fmt="o-", capsize=2, markersize=4,
                label="Empirical M")
    ax.plot(gammas, bound, "s--", markersize=3, alpha=0.6, label="Bound R²/γ²")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("γ  (log scale)")
    ax.set_ylabel("Number of mistakes M  (log scale)")
    ax.set_title("Perceptron mistakes as γ → 0  (d=50, R=1)")
    ax.legend()
    ax.grid(True, alpha=0.3, which="both")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "exp4_gamma_to_zero.png", dpi=150)
    plt.close(fig)
    print(f"  → saved exp4_gamma_to_zero.png\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Output directory: {OUTPUT_DIR.resolve()}\n")
    experiment_m_vs_inv_gamma_sq()
    experiment_tightness()
    experiment_dimension_independence()
    experiment_gamma_to_zero()
    print("All experiments complete.")
