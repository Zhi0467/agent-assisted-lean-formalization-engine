Statement extracted from Andy Jones, "A Clearer Proof of the Policy Gradient Theorem," pages 1-4 of the provided PDF, with the local analytic hypothesis made explicit so that the differentiation steps are honest.

Fix a finite state-action space. Let `p0` be the initial state-action distribution, `r` the reward vector, `Pi(theta)` the transition matrix induced by the policy parameter `theta`, `d(theta)` the state-action visitation-frequency row vector, `q(theta)` the state-action value column vector, and `J(theta)` the total reward.

Assume that `Pi`, `d`, `q`, and `J` are differentiable at the parameter value `theta`. Assume also that, on some neighborhood of `theta`, the Bellman identities

- `p0 = d(theta') (I - Pi(theta'))`
- `r = (I - Pi(theta')) q(theta')`

hold, and that on that same neighborhood the total reward may be written both as `J(theta') = d(theta') · r` and as `J(theta') = p0 · q(theta')`.

Then the derivative of the total reward at `theta` is

`J'(theta) = d(theta) Pi'(theta) q(theta)`.
