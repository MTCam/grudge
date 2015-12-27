"""Operator template mapper: BC-to-flux rewriting."""

from __future__ import division

__copyright__ = "Copyright (C) 2008 Andreas Kloeckner"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""


from pytools import memoize_method
from pymbolic.mapper import CSECachingMapperMixin
from grudge.symbolic.mappers import (
        IdentityMapper, DependencyMapper, CombineMapper,
        OperatorReducerMixin)
from grudge import sym
from grudge import sym_flux


class ExpensiveBoundaryOperatorDetector(CombineMapper):
    def combine(self, values):
        for val in values:
            if val:
                return True

        return False

    def map_operator_binding(self, expr):
        if isinstance(expr.op, sym.RestrictToBoundary):
            return False

        elif isinstance(expr.op, sym.FluxExchangeOperator):
            # FIXME: Duplication of these is an even bigger problem!
            return True

        elif isinstance(expr.op, (
                sym.QuadratureGridUpsampler,
                sym.QuadratureInteriorFacesGridUpsampler)):
            return True

        else:
            raise RuntimeError("Found '%s' in a boundary term. "
                    "To the best of my knowledge, no grudge operator applies "
                    "directly to boundary data, so this is likely in error."
                    % expr.op)

    def map_common_subexpression(self, expr):
        # If there are any expensive operators below here, this
        # CSE will catch them, so we can easily flux-CSE down to
        # here.

        return False

    def map_normal_component(self, expr):
        return False

    map_variable = map_normal_component
    map_constant = map_normal_component

    @memoize_method
    def __call__(self, expr):
        return CombineMapper.__call__(self, expr)


class BCToFluxRewriter(CSECachingMapperMixin, IdentityMapper):
    """Operates on :class:`FluxOperator` instances bound to
    :class:`BoundaryPair`. If the boundary pair's *bfield* is an expression of
    what's available in the *field*, we can avoid fetching the data for the
    explicit boundary condition and just substitute the *bfield* expression
    into the flux. This mapper does exactly that.
    """

    map_common_subexpression_uncached = \
            IdentityMapper.map_common_subexpression

    def __init__(self):
        self.expensive_bdry_op_detector = \
                ExpensiveBoundaryOperatorDetector()

    def map_operator_binding(self, expr):
        from grudge.symbolic.flux.mappers import FluxSubstitutionMapper

        if not (isinstance(expr.op, sym.FluxOperatorBase)
                and isinstance(expr.field, sym.BoundaryPair)):
            return IdentityMapper.map_operator_binding(self, expr)

        bpair = expr.field
        vol_field = bpair.field
        bdry_field = bpair.bfield
        flux = expr.op.flux

        bdry_dependencies = DependencyMapper(
                    include_calls="descend_args",
                    include_operator_bindings=True)(bdry_field)

        vol_dependencies = DependencyMapper(
                include_operator_bindings=True)(vol_field)

        vol_bdry_intersection = bdry_dependencies & vol_dependencies
        if vol_bdry_intersection:
            raise RuntimeError("Variables are being used as both "
                    "boundary and volume quantities: %s"
                    % ", ".join(str(v) for v in vol_bdry_intersection))

        # Step 1: Find maximal flux-evaluable subexpression of boundary field
        # in given BoundaryPair.

        class MaxBoundaryFluxEvaluableExpressionFinder(
                IdentityMapper, OperatorReducerMixin):

            def __init__(self, vol_expr_list, expensive_bdry_op_detector):
                self.vol_expr_list = vol_expr_list
                self.vol_expr_to_idx = dict((vol_expr, idx)
                        for idx, vol_expr in enumerate(vol_expr_list))

                self.bdry_expr_list = []
                self.bdry_expr_to_idx = {}

                self.expensive_bdry_op_detector = expensive_bdry_op_detector

            # {{{ expression registration
            def register_boundary_expr(self, expr):
                try:
                    return self.bdry_expr_to_idx[expr]
                except KeyError:
                    idx = len(self.bdry_expr_to_idx)
                    self.bdry_expr_to_idx[expr] = idx
                    self.bdry_expr_list.append(expr)
                    return idx

            def register_volume_expr(self, expr):
                try:
                    return self.vol_expr_to_idx[expr]
                except KeyError:
                    idx = len(self.vol_expr_to_idx)
                    self.vol_expr_to_idx[expr] = idx
                    self.vol_expr_list.append(expr)
                    return idx

            # }}}

            # {{{ map_xxx routines

            @memoize_method
            def map_common_subexpression(self, expr):
                # Here we need to decide whether this CSE should be turned into
                # a flux CSE or not. This is a good idea if the transformed
                # expression only contains "bare" volume or boundary
                # expressions.  However, as soon as an operator is applied
                # somewhere in the subexpression, the CSE should not be touched
                # in order to avoid redundant evaluation of that operator.
                #
                # Observe that at the time of this writing (Feb 2010), the only
                # operators that may occur in boundary expressions are
                # quadrature-related.

                has_expensive_operators = \
                        self.expensive_bdry_op_detector(expr.child)

                if has_expensive_operators:
                    return sym_flux.FieldComponent(
                            self.register_boundary_expr(expr),
                            is_interior=False)
                else:
                    return IdentityMapper.map_common_subexpression(self, expr)

            def map_normal(self, expr):
                raise RuntimeError("Your operator template contains a flux normal. "
                        "You may find this confusing, but you can't do that. "
                        "It turns out that you need to use "
                        "grudge.sym.normal() for normals in boundary "
                        "terms of operator templates.")

            def map_normal_component(self, expr):
                if expr.boundary_tag != bpair.tag:
                    raise RuntimeError("BoundaryNormalComponent and BoundaryPair "
                            "do not agree about boundary tag: %s vs %s"
                            % (expr.boundary_tag, bpair.tag))

                return sym_flux.Normal(expr.axis)

            def map_variable(self, expr):
                return sym_flux.FieldComponent(
                        self.register_boundary_expr(expr),
                        is_interior=False)

            map_subscript = map_variable

            def map_operator_binding(self, expr):
                if isinstance(expr.op, sym.RestrictToBoundary):
                    if expr.op.tag != bpair.tag:
                        raise RuntimeError("RestrictToBoundary and BoundaryPair "
                                "do not agree about boundary tag: %s vs %s"
                                % (expr.op.tag, bpair.tag))

                    return sym_flux.FieldComponent(
                            self.register_volume_expr(expr.field),
                            is_interior=True)

                elif isinstance(expr.op, sym.FluxExchangeOperator):
                    from grudge.mesh import TAG_RANK_BOUNDARY
                    op_tag = TAG_RANK_BOUNDARY(expr.op.rank)
                    if bpair.tag != op_tag:
                        raise RuntimeError("RestrictToBoundary and "
                                "FluxExchangeOperator do not agree about "
                                "boundary tag: %s vs %s"
                                % (op_tag, bpair.tag))
                    return sym_flux.FieldComponent(
                            self.register_boundary_expr(expr),
                            is_interior=False)

                elif isinstance(expr.op, sym.QuadratureBoundaryGridUpsampler):
                    if bpair.tag != expr.op.boundary_tag:
                        raise RuntimeError("RestrictToBoundary "
                                "and QuadratureBoundaryGridUpsampler "
                                "do not agree about boundary tag: %s vs %s"
                                % (expr.op.boundary_tag, bpair.tag))
                    return sym_flux.FieldComponent(
                            self.register_boundary_expr(expr),
                            is_interior=False)

                elif isinstance(expr.op, sym.QuadratureGridUpsampler):
                    # We're invoked before operator specialization, so we may
                    # see these instead of QuadratureBoundaryGridUpsampler.
                    return sym_flux.FieldComponent(
                            self.register_boundary_expr(expr),
                            is_interior=False)

                else:
                    raise RuntimeError("Found '%s' in a boundary term. "
                        "To the best of my knowledge, no grudge operator applies "
                        "directly to boundary data, so this is likely in error."
                        % expr.op)

            def map_flux_exchange(self, expr):
                return sym_flux.FieldComponent(
                        self.register_boundary_expr(expr),
                        is_interior=False)
            # }}}

        from pytools.obj_array import is_obj_array
        if not is_obj_array(vol_field):
            vol_field = [vol_field]

        mbfeef = MaxBoundaryFluxEvaluableExpressionFinder(list(vol_field),
                self.expensive_bdry_op_detector)

        new_bdry_field = mbfeef(bdry_field)

        # Step II: Substitute the new_bdry_field into the flux.
        def sub_bdry_into_flux(expr):
            if isinstance(expr, sym_flux.FieldComponent) and not expr.is_interior:
                if expr.index == 0 and not is_obj_array(bdry_field):
                    return new_bdry_field
                else:
                    return new_bdry_field[expr.index]
            else:
                return None

        new_flux = FluxSubstitutionMapper(sub_bdry_into_flux)(flux)

        from grudge.tools import is_zero
        from pytools.obj_array import make_obj_array
        if is_zero(new_flux):
            return 0
        else:
            return type(expr.op)(new_flux, *expr.op.__getinitargs__()[1:])(
                    sym.BoundaryPair(
                        make_obj_array([self.rec(e) for e in mbfeef.vol_expr_list]),
                        make_obj_array([self.rec(e) for e in mbfeef.bdry_expr_list]),
                        bpair.tag))
