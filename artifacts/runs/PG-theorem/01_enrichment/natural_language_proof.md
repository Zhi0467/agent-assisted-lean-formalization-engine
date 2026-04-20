# Natural-Language Proof

Under the stated assumptions, the value vector and visitation vector satisfy the fixed-point identities

- `d(θ) = d(θ) Π(θ) + p₀`
- `q(θ) = Π(θ) q(θ) + r`

or equivalently

- `p₀ = d(θ) (I - Π(θ))`
- `r = (I - Π(θ)) q(θ)`.

Differentiate the first identity with respect to a parameter coordinate `θ_i`. Since `p₀` does not depend on `θ`, the derivative is

`0 = (∂_i d(θ)) (I - Π(θ)) - d(θ) (∂_i Π(θ))`.

Rearranging gives

`(∂_i d(θ)) (I - Π(θ)) = d(θ) (∂_i Π(θ))`.

Now differentiate the second identity. Since `r` is also parameter-independent, we get

`0 = -(∂_i Π(θ)) q(θ) + (I - Π(θ)) (∂_i q(θ))`,

so

`(I - Π(θ)) (∂_i q(θ)) = (∂_i Π(θ)) q(θ)`.

Finally, differentiate the total return. Using `J(θ) = d(θ) · r`,

`∂_i J(θ) = (∂_i d(θ)) · r`.

Substitute the fixed-point formula `r = (I - Π(θ)) q(θ)`:

`∂_i J(θ) = (∂_i d(θ)) (I - Π(θ)) q(θ)`.

Now apply the differentiated first fixed-point identity:

`∂_i J(θ) = d(θ) (∂_i Π(θ)) q(θ)`.

This is exactly the policy gradient formula.

The same conclusion also follows symmetrically from `J(θ) = p₀ · q(θ)` together with the differentiated equation for `q(θ)`. The proof therefore uses only the fixed-point identities for `d` and `q`, plus ordinary product-rule differentiation.
