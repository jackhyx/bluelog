# -*- coding: utf-8 -*-
"""
    :author: Grey Li (李辉)
    :url: http://greyli.com
    :copyright: © 2018 Grey Li <withlihui@gmail.com>
    :license: MIT, see LICENSE for more details.
"""
from flask import render_template, flash, redirect, url_for, request, current_app, Blueprint, abort, make_response
from flask_login import current_user

from bluelog.emails import send_new_comment_email, send_new_reply_email
from bluelog.extensions import db
from bluelog.forms import CommentForm, AdminCommentForm
from bluelog.models import Post, Category, Comment
from bluelog.utils import redirect_back
# 实例化 ： 不仅仅是对视图函数分类，将程序某一部分的所有操作组织在一起；
# 不仅在代码层面上的组织程序，还可以在程序层面上定义属性，为蓝本设置子域名
# _bp后缀区分蓝本对象，避免潜在的命名冲突
# 参数1：蓝本名称 参数2：包或模块的名称
blog_bp = Blueprint('blog', __name__)


@blog_bp.route('/')
def index():
    # 从查询字符串获取当前页数从request.args中获取；没有设置则默认值1，指定int类型保证在参数类型错误时使用默认值；
    page = request.args.get('page', 1, type=int)
    # 每页数量 从配置变量获取方便统一修改
    per_page = current_app.config['BLUELOG_POST_PER_PAGE']
    # 分页对象 为了实现分页 把查询执行函数all()换成paginate()
    # page:返回那一页记录 peri_page: 把记录分成几页
    # def paginate(self, page=None, per_page=None, error_out=True, max_per_page=None)
    # error_out:当前查询页数超出行为：True 页面超过最大值，page/per_page为负数或者非整型数返回404；False返回空记录
    # max_per_page 每页数量最大值
    # 如果没有page 和 per_page Flask-SQLAlchemy 自动获取 默认 1 20
    pagination = Post.query.order_by(Post.timestamp.desc()).paginate(page, per_page=per_page)
    # pagination实例：分页对象->包含分页信息 调用items属性以列表形式返回对应页数（默认1）的记录
    # 类属性 has_next 如果存在下一页，返回True has_prev如果存在上一页 返回True
    # 可以在html中通过此状态渲染按钮状态
    posts = pagination.items # 当前页数的记录列表
    return render_template('blog/index.html', pagination=pagination, posts=posts)


@blog_bp.route('/about')
def about():
    return render_template('blog/about.html')


@blog_bp.route('/category/<int:category_id>')
def show_category(category_id): # 显示分类文章列表
    category = Category.query.get_or_404(category_id) # 获取对应分类记录
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config['BLUELOG_POST_PER_PAGE']
    pagination = Post.query.with_parent(category).order_by(Post.timestamp.desc()).paginate(page, per_page)
    posts = pagination.items
    return render_template('blog/category.html', category=category, pagination=pagination, posts=posts)


@blog_bp.route('/post/<int:post_id>', methods=['GET', 'POST'])
def show_post(post_id):
    post = Post.query.get_or_404(post_id) # 获取对应文章
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config['BLUELOG_COMMENT_PER_PAGE']
    # Comment.query.with_parent(post) 获取文章所属评论；同时排序和分页
    # filter_by(reviewed=True) 筛选通过审核的评论记录
    pagination = Comment.query.with_parent(post).filter_by(reviewed=True).order_by(Comment.timestamp.asc()).paginate(
        page, per_page)
    comments = pagination.items
    # 验证和保存
    # 如果当前用户已登录，使用管理员表单
    # current_user.is_authenticated Flask-Login导入 bool值代表当前用户的登录状态
    if current_user.is_authenticated:
        form = AdminCommentForm()

        form.author.data = current_user.name
        form.email.data = current_app.config['BLUELOG_EMAIL']
        form.site.data = url_for('.index')

        from_admin = True
        reviewed = True

    else:
    # 未登录使用普通表单
        form = CommentForm()
        from_admin = False
        reviewed = False

    # 获取数据并保存
    if form.validate_on_submit():
        author = form.author.data
        email = form.email.data
        site = form.site.data
        body = form.body.data
        comment = Comment(
            author=author, email=email, site=site, body=body,
            from_admin=from_admin, post=post, reviewed=reviewed)
        replied_id = request.args.get('reply')
        if replied_id:
            replied_comment = Comment.query.get_or_404(replied_id)
            comment.replied = replied_comment
            send_new_reply_email(replied_comment)
        db.session.add(comment)
        db.session.commit()
        # 根据登录状态显示不同的提示消息
        if current_user.is_authenticated:  # send message based on authentication status
            flash('Comment published.', 'success')

        else:
            flash('Thanks, your comment will be published after reviewed.', 'info')
            # 向管理员发送提醒邮件，传入post
            send_new_comment_email(post)
        return redirect(url_for('.show_post', post_id=post_id))
    return render_template('blog/post.html', post=post, pagination=pagination, form=form, comments=comments)


@blog_bp.route('/reply/comment/<int:comment_id>')
# 显示回复评论标记
# 将接受的数据通过查询字符串传递给了需要评论的photo视图
def reply_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if not comment.post.can_comment:
        flash('Comment is disabled.', 'warning')
        return redirect(url_for('.show_post', post_id=comment.post.id))
    return redirect(
        # 重定向到原来的文章界面
        # reply 被回复的评论id
        # author 被回复的评论的作者
        # ”#comment-form“ 将页面焦点跳到评论表单的位置
        # 任何多余的关键字参数都会被自动转换为查询字符串
        url_for('.show_post', post_id=comment.post_id, reply=comment_id, author=comment.author) + '#comment-form')


@blog_bp.route('/change-theme/<theme_name>')
def change_theme(theme_name):
    if theme_name not in current_app.config['BLUELOG_THEMES'].keys():
        abort(404)

    response = make_response(redirect_back())
    response.set_cookie('theme', theme_name, max_age=30 * 24 * 60 * 60)
    return response
