"""Operator template type inference."""

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

import pymbolic.mapper


# {{{ representation tags

class NodalRepresentation(object):
    """A tag representing nodal representation.

    Volume and boundary vectors below are represented either nodally or on a
    quadrature grid. This tag expresses one of the two.
    """
    def __repr__(self):
        return "Nodal"

    def __eq__(self, other):
        return type(self) == type(other)

    def __ne__(self, other):
        return not self.__eq__(other)


class QuadratureRepresentation(object):
    """A tag representing representation on a quadrature grid tagged with
    *quadrature_tag".

    Volume and boundary vectors below are represented either nodally or on a
    quadrature grid. This tag expresses one of the two.
    """
    def __init__(self, quadrature_tag):
        self.quadrature_tag = quadrature_tag

    def __eq__(self, other):
        return (type(self) == type(other)
                and self.quadrature_tag == other.quadrature_tag)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "Quadrature(%r)" % self.quadrature_tag

# }}}


# {{{ type information --------------------------------------------------------

class type_info:
    """These classes represent various bits and pieces of information that
    we may deduce about expressions in our optemplate.
    """

    # serves only as a namespace, thus lower case

    # {{{ generic type info base classes
    class TypeInfo(object):
        def unify(self, other, expr=None):
            """Return a type that can represent both *self* and *other*.
            If impossible, raise :exc:`TypeError`. Subtypes should override
            :meth:`unify_inner`.
            """
            # shortcut
            if self == other:
                return self

            u_s_o = self.unify_inner(other)
            u_o_s = other.unify_inner(self)

            if u_s_o is NotImplemented:
                if u_o_s is NotImplemented:
                    if expr is not None:
                        from grudge.optemplate.tools import pretty
                        raise TypeError("types '%s' and '%s' for '%s' "
                                "cannot be unified" % (self, other,
                                    pretty(expr)))
                    else:
                        raise TypeError("types '%s' and '%s' cannot be unified"
                                % (self, other))
                else:
                    return u_o_s
            elif u_o_s is NotImplemented:
                return u_s_o

            if u_s_o != u_o_s:
                raise RuntimeError("types '%s' and '%s' don't agree about "
                        "their unifier" % (self, other))
            return u_s_o

        def unify_inner(self, other):
            """Actual implementation that tries to unify self and other.
            May return *NotImplemented* to indicate that the reverse unification
            should be tried. This methods is overriden by derived classes.
            Derived classes should delegate to base classes if they don't know the
            answer.
            """
            return NotImplemented

        def __eq__(self, other):
            return (type(self) == type(other)
                    and self.__getinitargs__() == other.__getinitargs__())

        def __ne__(self, other):
            return not self.__eq__(other)

    class StatelessTypeInfo(TypeInfo):
        def __getinitargs__(self):
            return ()

    class FinalType(TypeInfo):
        """If a :class:`TypeInfo` instance is also an instance of this class,
        no more information can be added about this type. As a result, this
        type only unifies with equal instances.
        """
    # }}}

    # {{{ simple types: no type, scalar
    class NoType(StatelessTypeInfo):
        """Represents "nothing known about type"."""
        def unify_inner(self, other):
            return other

        def __repr__(self):
            return "NoType"

    # this singleton should be the only instance ever created of NoType
    no_type = NoType()

    class Scalar(StatelessTypeInfo, FinalType):
        def __repr__(self):
            return "Scalar"
    # }}}

    # {{{ tagged type base classes: representation, domain
    class VectorRepresentationBase(object):
        def __init__(self, repr_tag):
            self.repr_tag = repr_tag

        def __getinitargs__(self):
            return (self.repr_tag,)

    class VolumeVectorBase(object):
        def __getinitargs__(self):
            return ()

    class InteriorFacesVectorBase(object):
        def __getinitargs__(self):
            return ()

    class BoundaryVectorBase(object):
        def __init__(self, boundary_tag):
            self.boundary_tag = boundary_tag

        def __getinitargs__(self):
            return (self.boundary_tag,)
    # }}}

    # {{{ single-aspect-known unification helper types
    class KnownVolume(TypeInfo, VolumeVectorBase):
        """Type information indicating that this must be a volume vector
        of unknown representation.
        """

        def __repr__(self):
            return "KnownAsVolume"

        def unify_inner(self, other):
            # Unification with KnownRepresentation is handled in KnownRepresentation.
            # Here, we only need to unify with VolumeVector.

            if isinstance(other, type_info.VolumeVector):
                return other
            else:
                return type_info.TypeInfo.unify_inner(self, other)

    class KnownInteriorFaces(TypeInfo, InteriorFacesVectorBase):
        """Type information indicating that this must be a vector
        of interior face values.

        .. note::

            These vectors are only necessary in a quadrature setting.
        """

        def __repr__(self):
            return "KnownAsIntFace"

        def unify_inner(self, other):
            # Unification with KnownRepresentation is handled in KnownRepresentation.
            # Here, we only need to unify with InteriorFacesVector.

            if isinstance(other, type_info.InteriorFacesVector):
                return other
            elif isinstance(other, type_info.KnownVolume):
                return type_info.VolumeVector(NodalRepresentation())
            elif other == type_info.VolumeVector(NodalRepresentation()):
                return other
            else:
                return type_info.TypeInfo.unify_inner(self, other)

    class KnownBoundary(TypeInfo, BoundaryVectorBase):
        """Type information indicating that this must be a boundary vector."""

        def __repr__(self):
            return "KnownAsBoundary(%s)" % self.boundary_tag

        def unify_inner(self, other):
            # Unification with KnownRepresentation is handled in KnownRepresentation.
            # Here, we only need to unify with BoundaryVector.

            if (isinstance(other, type_info.BoundaryVector)
                    and self.boundary_tag == other.boundary_tag):
                return other
            else:
                return type_info.TypeInfo.unify_inner(self, other)

    class KnownRepresentation(TypeInfo, VectorRepresentationBase):
        """Type information indicating that the representation (see
        representation tags, above) is known, but nothing else (e.g. whether
        this is a boundary or volume vector).
        """
        def __repr__(self):
            return "KnownRepresentation(%s)" % self.repr_tag

        def unify_inner(self, other):
            if (isinstance(other, type_info.VolumeVector)
                    and self.repr_tag == other.repr_tag):
                return other
            elif (isinstance(other, type_info.BoundaryVector)
                    and self.repr_tag == other.repr_tag):
                return other
            elif isinstance(other, type_info.KnownVolume):
                return type_info.VolumeVector(self.repr_tag)
            elif isinstance(other, type_info.KnownInteriorFaces):
                if isinstance(self.repr_tag, NodalRepresentation):
                    return type_info.VolumeVector(self.repr_tag)
                else:
                    return type_info.InteriorFacesVector(self.repr_tag)
            elif isinstance(other, type_info.KnownBoundary):
                return type_info.BoundaryVector(other.boundary_tag, self.repr_tag)
            else:
                return type_info.TypeInfo.unify_inner(self, other)
    # }}}

    # {{{ fully specified grudge data types
    class VolumeVector(FinalType, VectorRepresentationBase, VolumeVectorBase):
        def __repr__(self):
            return "Volume(%s)" % self.repr_tag

    class InteriorFacesVector(FinalType, VectorRepresentationBase,
            InteriorFacesVectorBase):
        def __init__(self, repr_tag):
            if not isinstance(repr_tag, QuadratureRepresentation):
                raise TypeError("InteriorFacesVector is not usable with non-"
                        "quadrature representations")
            type_info.VectorRepresentationBase.__init__(self, repr_tag)

        def __repr__(self):
            return "InteriorFaces(%s)" % self.repr_tag

    class BoundaryVector(FinalType, BoundaryVectorBase,
            VectorRepresentationBase):
        def __init__(self, boundary_tag, repr_tag):
            type_info.BoundaryVectorBase.__init__(self, boundary_tag)
            type_info.VectorRepresentationBase.__init__(self, repr_tag)

        def __repr__(self):
            return "Boundary(%s, %s)" % (self.boundary_tag, self.repr_tag)

        def __getinitargs__(self):
            return (self.boundary_tag, self.repr_tag)
    # }}}


# {{{ aspect extraction functions

def extract_representation(ti):
    try:
        own_repr_tag = ti.repr_tag
    except AttributeError:
        return type_info.no_type
    else:
        return type_info.KnownRepresentation(own_repr_tag)


def extract_domain(ti):
    if isinstance(ti, type_info.VolumeVectorBase):
        return type_info.KnownVolume()
    elif isinstance(ti, type_info.BoundaryVectorBase):
        return type_info.KnownBoundary(ti.boundary_tag)
    else:
        return type_info.no_type

# }}}

# }}}


# {{{ TypeDict helper type

class TypeDict(object):
    def __init__(self, hints):
        self.container = hints.copy()
        self.change_flag = False

    def __getitem__(self, expr):
        try:
            return self.container[expr]
        except KeyError:
            return type_info.no_type

    def __setitem__(self, expr, new_tp):
        if new_tp is type_info.no_type:
            return

        try:
            old_tp = self.container[expr]
        except KeyError:
            self.container[expr] = new_tp
            self.change_flag = True
        else:
            tp = old_tp.unify(new_tp, expr)
            if tp != old_tp:
                self.change_flag = True
                self.container[expr] = tp

    def iteritems(self):
        return self.container.iteritems()

# }}}


# {{{ type inference mapper

class TypeInferrer(pymbolic.mapper.RecursiveMapper):
    def __init__(self):
        self.cse_last_results = {}

    def __call__(self, expr, type_hints={}):
        typedict = TypeDict(type_hints)

        while True:
            typedict.change_flag = False

            def infer_for_expr(expr):
                tp = pymbolic.mapper.RecursiveMapper.__call__(self, expr, typedict)
                typedict[expr] = tp

            # Numpy arrays occur either at the top level or in flux
            # expressions. This code handles the top level case.
            from pytools.obj_array import with_object_array_or_scalar
            with_object_array_or_scalar(infer_for_expr, expr)

            if not typedict.change_flag:
                # nothing has changed any more, type information has 'converged'
                break

        # check that type inference completed successfully
        for expr, tp in typedict.iteritems():
            if not isinstance(tp, type_info.FinalType):
                raise RuntimeError("type inference was unable to deduce "
                        "complete type information for '%s' (only '%s')"
                        % (expr, tp))

        return typedict

    def rec(self, expr, typedict):
        tp = pymbolic.mapper.RecursiveMapper.rec(self, expr, typedict)
        typedict[expr] = tp
        return tp

    # Information needs to propagate upward (toward the leaves) *and*
    # downward (toward the roots) in the expression tree.

    # {{{ base cases
    def infer_for_children(self, expr, typedict, children):
        # This routine allows scalars among children and treats them as
        # not type-changing

        tp = typedict[expr]

        non_scalar_exprs = []

        for child in children:
            if tp is type_info.no_type:
                tp = self.rec(child, typedict)
                if isinstance(tp, type_info.Scalar):
                    tp = type_info.no_type
                else:
                    non_scalar_exprs.append(child)
            else:
                other_tp = self.rec(child, typedict)

                if not isinstance(other_tp, type_info.Scalar):
                    non_scalar_exprs.append(child)
                    tp = tp.unify(other_tp, child)

        for child in non_scalar_exprs:
            typedict[child] = tp

        if not non_scalar_exprs:
            tp = type_info.Scalar()

        return tp

    # }}}

    def map_sum(self, expr, typedict):
        return self.infer_for_children(expr, typedict, expr.children)

    def map_product(self, expr, typedict):
        return self.infer_for_children(expr, typedict, expr.children)

    def map_quotient(self, expr, typedict):
        return self.infer_for_children(expr, typedict,
                children=[expr.numerator, expr.denominator])

    def map_power(self, expr, typedict):
        return self.infer_for_children(expr, typedict,
                children=[expr.base, expr.exponent])

    def map_if(self, expr, typedict):
        return self.infer_for_children(expr, typedict,
                children=[expr.condition, expr.then, expr.else_])

    def map_comparison(self, expr, typedict):
        return self.infer_for_children(expr, typedict,
                children=[expr.left, expr.right])

    def map_if_positive(self, expr, typedict):
        return self.infer_for_children(expr, typedict,
                children=[expr.criterion, expr.then, expr.else_])

    def map_call(self, expr, typedict):
        # assumes functions to be non-type-changing
        return self.infer_for_children(expr, typedict,
                children=expr.parameters)

    def map_operator_binding(self, expr, typedict):
        from grudge.optemplate.operators import (
                NodalReductionOperator,

                DiffOperatorBase,
                ReferenceDiffOperatorBase,

                MassOperatorBase,
                ReferenceMassOperatorBase,

                ElementwiseMaxOperator,
                BoundarizeOperator, FluxExchangeOperator,
                FluxOperatorBase,
                QuadratureGridUpsampler, QuadratureBoundaryGridUpsampler,
                QuadratureInteriorFacesGridUpsampler,

                MassOperator,
                ReferenceMassOperator,
                ReferenceQuadratureMassOperator,

                StiffnessTOperator,
                ReferenceStiffnessTOperator,
                ReferenceQuadratureStiffnessTOperator,

                ElementwiseLinearOperator)

        if isinstance(expr.op, NodalReductionOperator):
            typedict[expr.field] = type_info.KnownVolume()
            self.rec(expr.field, typedict)
            return type_info.Scalar()

        elif isinstance(expr.op,
                (ReferenceQuadratureStiffnessTOperator,
                    ReferenceQuadratureMassOperator)):
            typedict[expr.field] = type_info.VolumeVector(
                    QuadratureRepresentation(expr.op.quadrature_tag))
            self.rec(expr.field, typedict)
            return type_info.VolumeVector(NodalRepresentation())

        elif isinstance(expr.op,
                (ReferenceStiffnessTOperator, StiffnessTOperator)):
            # stiffness_T can be specialized for quadrature by OperatorSpecializer
            typedict[expr.field] = type_info.KnownVolume()
            self.rec(expr.field, typedict)
            return type_info.VolumeVector(NodalRepresentation())

        elif isinstance(expr.op,
                (ReferenceMassOperator, MassOperator)):
            # mass can be specialized for quadrature by OperatorSpecializer
            typedict[expr.field] = type_info.KnownVolume()
            self.rec(expr.field, typedict)
            return type_info.VolumeVector(NodalRepresentation())

        elif isinstance(expr.op, (
                DiffOperatorBase,
                ReferenceDiffOperatorBase,
                MassOperatorBase,
                ReferenceMassOperatorBase)):
            # all other operators are purely nodal
            typedict[expr.field] = type_info.VolumeVector(NodalRepresentation())
            self.rec(expr.field, typedict)
            return type_info.VolumeVector(NodalRepresentation())

        elif isinstance(expr.op, ElementwiseMaxOperator):
            typedict[expr.field] = typedict[expr].unify(
                    type_info.KnownVolume(), expr.field)
            return self.rec(expr.field, typedict)

        elif isinstance(expr.op, BoundarizeOperator):
            # upward propagation: argument has same rep tag as result
            typedict[expr.field] = type_info.KnownVolume().unify(
                    extract_representation(type_info), expr.field)

            self.rec(expr.field, typedict)

            # downward propagation: result has same rep tag as argument
            return type_info.KnownBoundary(expr.op.tag).unify(
                    extract_representation(typedict[expr.field]), expr)

        elif isinstance(expr.op, FluxExchangeOperator):
            raise NotImplementedError

        elif isinstance(expr.op, FluxOperatorBase):
            from pytools.obj_array import with_object_array_or_scalar
            from grudge.optemplate.primitives import BoundaryPair

            repr_tag_cell = [type_info.no_type]

            def process_vol_flux_arg(flux_arg):
                typedict[flux_arg] = type_info.KnownInteriorFaces() \
                        .unify(repr_tag_cell[0], flux_arg)
                repr_tag_cell[0] = extract_representation(
                        self.rec(flux_arg, typedict))

            if isinstance(expr.field, BoundaryPair):
                def process_bdry_flux_arg(flux_arg):
                    typedict[flux_arg] = type_info.KnownBoundary(bpair.tag) \
                        .unify(repr_tag_cell[0], flux_arg)

                    repr_tag_cell[0] = extract_representation(
                            self.rec(flux_arg, typedict))

                bpair = expr.field
                with_object_array_or_scalar(process_vol_flux_arg, bpair.field)
                with_object_array_or_scalar(process_bdry_flux_arg, bpair.bfield)
            else:
                with_object_array_or_scalar(process_vol_flux_arg, expr.field)

            return type_info.VolumeVector(NodalRepresentation())

        elif isinstance(expr.op, QuadratureGridUpsampler):
            typedict[expr.field] = extract_domain(typedict[expr])
            self.rec(expr.field, typedict)
            return type_info.KnownRepresentation(
                    QuadratureRepresentation(expr.op.quadrature_tag))\
                            .unify(extract_domain(typedict[expr.field]), expr)

        elif isinstance(expr.op, QuadratureInteriorFacesGridUpsampler):
            typedict[expr.field] = type_info.VolumeVector(
                    NodalRepresentation())
            self.rec(expr.field, typedict)
            return type_info.InteriorFacesVector(
                    QuadratureRepresentation(expr.op.quadrature_tag))

        elif isinstance(expr.op, QuadratureBoundaryGridUpsampler):
            typedict[expr.field] = type_info.BoundaryVector(
                    expr.op.boundary_tag, NodalRepresentation())
            self.rec(expr.field, typedict)
            return type_info.BoundaryVector(
                    expr.op.boundary_tag,
                    QuadratureRepresentation(expr.op.quadrature_tag))

        elif isinstance(expr.op, ElementwiseLinearOperator):
            typedict[expr.field] = type_info.VolumeVector(NodalRepresentation())
            self.rec(expr.field, typedict)
            return type_info.VolumeVector(NodalRepresentation())

        else:
            raise RuntimeError("TypeInferrer doesn't know how to handle '%s'"
                    % expr.op)

    def map_whole_domain_flux(self, expr, typedict):
        repr_tag_cell = [type_info.no_type]

        def process_vol_flux_arg(flux_arg):
            typedict[flux_arg] = type_info.KnownInteriorFaces() \
                    .unify(repr_tag_cell[0], flux_arg)
            repr_tag_cell[0] = extract_representation(
                    self.rec(flux_arg, typedict))

        def process_bdry_flux_arg(flux_arg):
            typedict[flux_arg] = type_info.KnownBoundary(bpair.tag) \
                .unify(repr_tag_cell[0], flux_arg)

            repr_tag_cell[0] = extract_representation(
                    self.rec(flux_arg, typedict))

        from pytools.obj_array import with_object_array_or_scalar
        for int_flux_info in expr.interiors:
            with_object_array_or_scalar(process_vol_flux_arg,
                    int_flux_info.field_expr)

        for bdry_flux_info in expr.boundaries:
            bpair = bdry_flux_info.bpair
            with_object_array_or_scalar(process_vol_flux_arg, bpair.field)
            with_object_array_or_scalar(process_bdry_flux_arg, bpair.bfield)

        return type_info.VolumeVector(NodalRepresentation())

    def map_flux_exchange(self, expr, typedict):
        for arg in expr.arg_fields:
            typedict[arg] = type_info.VolumeVector(NodalRepresentation())

        from grudge.mesh import TAG_RANK_BOUNDARY
        return type_info.BoundaryVector(
                TAG_RANK_BOUNDARY(expr.rank),
                NodalRepresentation())

    def map_constant(self, expr, typedict):
        return type_info.Scalar().unify(typedict[expr], expr)

    def map_variable(self, expr, typedict):
        # user-facing variables are nodal
        return type_info.KnownRepresentation(NodalRepresentation())\
                .unify(typedict[expr], expr)

    map_subscript = map_variable

    def map_scalar_parameter(self, expr, typedict):
        return type_info.Scalar().unify(typedict[expr], expr)

    def map_ones(self, expr, typedict):
        # FIXME: This is a bit dumb. If the quadrature_tag is None,
        # we don't know whether the expression was specialized
        # to 'no quadrature' or if it simply does not know yet
        # whether it will be on a quadrature grid.
        if expr.quadrature_tag is not None:
            return (type_info.VolumeVector(
                QuadratureRepresentation(expr.quadrature_tag))
                .unify(typedict[expr], expr))
        else:
            return (type_info.VolumeVector(NodalRepresentation())
                    .unify(typedict[expr], expr))

    def map_node_coordinate_component(self, expr, typedict):
        # FIXME: This is a bit dumb. If the quadrature_tag is None,
        # we don't know whether the expression was specialized
        # to 'no quadrature' or if it simply does not know yet
        # whether it will be on a quadrature grid.
        if expr.quadrature_tag is not None:
            return (type_info.VolumeVector(
                QuadratureRepresentation(expr.quadrature_tag))
                .unify(typedict[expr], expr))
        else:
            return (type_info.VolumeVector(NodalRepresentation())
                    .unify(typedict[expr], expr))

    def map_normal_component(self, expr, typedict):
        # FIXME: This is a bit dumb. If the quadrature_tag is None,
        # we don't know whether the expression was specialized
        # to 'no quadrature' or if it simply does not know yet
        # whether it will be on a quadrature grid.

        if expr.quadrature_tag is not None:
            return (type_info.BoundaryVector(expr.boundary_tag,
                QuadratureRepresentation(expr.quadrature_tag))
                .unify(typedict[expr], expr))
        else:
            return (type_info.KnownBoundary(expr.boundary_tag)
                    .unify(typedict[expr], expr))

    def map_jacobian(self, expr, typedict):
        return type_info.KnownVolume()

    map_forward_metric_derivative = map_jacobian
    map_inverse_metric_derivative = map_jacobian

    def map_common_subexpression(self, expr, typedict):
        outer_tp = typedict[expr]

        last_tp = self.cse_last_results.get(expr, type_info.no_type)
        if outer_tp != last_tp or last_tp == type_info.no_type:
            # re-run inner type inference with new outer information
            typedict[expr.child] = outer_tp
            new_tp = self.rec(expr.child, typedict)

            # For correct caching, we need to make sure that
            # information below this level has fully propagated.
            while True:
                typedict.change_flag = False
                new_tp = self.rec(expr.child, typedict)

                if not typedict.change_flag:
                    # nothing has changed any more
                    break

            self.cse_last_results[expr] = new_tp
            typedict[expr.child] = new_tp

            # we can be sure we *have* changed something
            typedict.change_flag = True
            return new_tp
        else:
            return last_tp

# }}}


# vim: foldmethod=marker
