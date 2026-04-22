Jones's page-4 proof is algebraic: once the Bellman identities and their differentiated forms are available, the policy-gradient identity follows by a short chain of substitutions. The only extra work needed for a formal target is to state local hypotheses strong enough to justify those differentiated identities at the chosen parameter value `theta`.

Because `J(theta') = d(theta') · r` on a neighborhood of `theta` and `r` is constant, differentiating at `theta` gives

`J'(theta) = d'(theta) · r`.

Because `p0 = d(theta') (I - Pi(theta'))` on a neighborhood of `theta` and `p0` is constant, differentiating that identity at `theta` and applying the product rule gives

`0 = d'(theta) (I - Pi(theta)) - d(theta) Pi'(theta)`,

so

`d'(theta) (I - Pi(theta)) = d(theta) Pi'(theta)`.

Now use the Bellman identity `r = (I - Pi(theta)) q(theta)` at `theta`. Substituting this into the formula for `J'(theta)` yields

`J'(theta) = d'(theta) · r = d'(theta) (I - Pi(theta)) q(theta) = d(theta) Pi'(theta) q(theta)`.

This is exactly the left-hand derivation Jones gives on page 4. The symmetric argument starting from `J(theta') = p0 · q(theta')` and differentiating `r = (I - Pi(theta')) q(theta')` gives the same conclusion. The source therefore provides the proof pattern; the strengthened local hypotheses only make explicit the analytic assumptions that the PDF leaves implicit.
